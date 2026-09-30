"""Скачивает советские нормативы (РТМ/ОСТ/РД/ГОСТ) с files.stroyinf.ru для OCR-датасета.

    python scripts/scrape/stroyinf.py --out data/stroyinf --limit 50

Результат в --out:
  pdf/<id>.pdf     — исходные сканы; папку можно отдавать backend'у как input_dir;
  documents.jsonl  — по строке на документ: обозначение, название, год, url,
                     sha256 файла и диагностика текстового слоя.

Повторный запуск продолжает: документы из documents.jsonl пропускаются, уже
лежащий на диске PDF не качается заново, файл с тем же sha256 под другим
id не сохраняется (дубль). --limit — размер набора в целом, а не за запуск.

Диагностика слоя (поле "layer"): у PDF есть невидимый текстовый слой — чужое
OCR, на машинописи часто плохое или целиком мусорное. Скрипт его не разбирает,
а только оценивает тем же постраничным правилом, что и backend
(pdf_extract.page_text_layer_usable): "recommend": "text_layer" (слой годится
на всех страницах), "mixed" (часть страниц уйдёт в OCR) или "ocr", плюс
качество по страницам.

Нужны requests и зависимости backend/pdf_extract.py (pypdfium2, numpy);
эвристики слоя — общие с backend (backend/text_layer_quality.py).
"""

import argparse
import hashlib
import html
import json
import re
import sys
import time
from pathlib import Path

import pypdfium2 as pdfium
import requests

# backend/ импортируется абсолютно (backend.*) — нужен корень репозитория в пути
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from backend import pdf_extract, text_layer_quality  # noqa: E402

BASE_URL = "https://files.stroyinf.ru"
DEFAULT_GROUPS = ["РТМ", "ОСТ", "РД", "ГОСТ"]
DEFAULT_USER_AGENT = "ocr-markup-stroyinf-scraper/1.0 (https://github.com/ErshovVE/ocr_markup)"
MAX_RETRIES = 5
MAX_LIST_PAGES = 1000  # предохранитель от бесконечной пагинации

_ROW = re.compile(r"<tr class='m3'>(.*?)</tr>", re.S)
_CELL = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
_PDF = re.compile(r"href='(https?://[^']+/Data2?/[^']+\.pdf)'[^>]*title='([^']*)'")
_DATE = re.compile(r"\b\d{2}\.\d{2}\.(\d{4})\b")
_TAG = re.compile(r"<[^>]+>")


def _text(fragment: str) -> str:
    return " ".join(html.unescape(_TAG.sub(" ", fragment)).split())


def decode_html(raw: bytes) -> str:
    """Страницы stroyinf в utf-8, но на всякий случай — откат на cp1251."""
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp1251", errors="replace")


def parse_groups(page: str) -> dict:
    """Главная /list2.htm -> {название группы: id каталога}."""
    return {
        html.unescape(name).strip(): gid
        for gid, name in re.findall(r"href='/list2/(\d+)-0\.htm'[^>]*>([^<]+)</a>", page)
    }


def parse_catalog(page: str) -> list:
    """Страница каталога -> [{id, designation, title, date, status, pdf_url}]."""
    docs = []
    for row in _ROW.findall(page):
        link = _PDF.search(row)
        cells = _CELL.findall(row)
        if not link or len(cells) < 4:
            continue
        url, designation = link.groups()
        docs.append(
            {
                "id": Path(url).stem,
                "designation": html.unescape(designation).strip(),
                "title": _text(cells[1]),
                "date": _text(cells[2]),
                "status": _text(cells[3]),
                "pdf_url": url,
            }
        )
    return docs


def doc_year(doc: dict):
    """Год документа: из даты введения, иначе из хвоста обозначения ('РТМ 3-72-70')."""
    match = _DATE.search(doc.get("date", ""))
    if match:
        return int(match.group(1))
    tail = re.search(r"[-–](\d{2}|\d{4})\s*$", doc.get("designation", ""))
    if not tail:
        return None
    year = int(tail.group(1))
    if year >= 100:
        return year
    return 1900 + year if year > 25 else 2000 + year


def diagnose_pdf(path: Path) -> dict:
    pdf = pdfium.PdfDocument(str(path))
    try:
        return text_layer_quality.diagnose_layer(
            [pdf_extract.page_words(pdf[i]) for i in range(len(pdf))]
        )
    finally:
        pdf.close()


class StroyinfClient:
    def __init__(self, session: requests.Session, delay: float = 1.0, base_url: str = BASE_URL):
        self.session = session
        self.delay = delay
        self.base_url = base_url

    def get(self, url: str) -> requests.Response:
        for attempt in range(MAX_RETRIES):
            try:
                resp = self.session.get(url, timeout=120)
            except requests.RequestException as exc:
                print(f"  сетевая ошибка ({exc}); повтор", file=sys.stderr)
                time.sleep(2**attempt)
                continue
            if resp.status_code in (429, 500, 502, 503, 504):
                time.sleep(int(resp.headers.get("Retry-After") or 2**attempt))
                continue
            resp.raise_for_status()
            time.sleep(self.delay)
            return resp
        raise RuntimeError(f"не удалось получить {url} за {MAX_RETRIES} попыток")

    def groups(self) -> dict:
        return parse_groups(decode_html(self.get(f"{self.base_url}/list2.htm").content))

    def catalog(self, gid: str, group: str):
        for n in range(MAX_LIST_PAGES):
            page = decode_html(self.get(f"{self.base_url}/list2/{gid}-{n}.htm").content)
            docs = parse_catalog(page)
            if not docs:
                return
            for doc in docs:
                yield {**doc, "group": group}
            if f"/list2/{gid}-{n + 1}.htm" not in page:
                return


def round_robin(iterables):
    """По одному элементу из каждого источника по очереди — выборка разнообразнее."""
    iterators = [iter(it) for it in iterables]
    while iterators:
        alive = []
        for it in iterators:
            item = next(it, None)
            if item is not None:
                alive.append(it)
                yield item
        iterators = alive


def iter_candidates(client: StroyinfClient, args):
    groups = client.groups()
    catalogs = []
    for name in args.group:
        if name not in groups:
            print(f"группа «{name}» не найдена на сайте, пропуск", file=sys.stderr)
            continue
        catalogs.append(client.catalog(groups[name], name))
    for doc in round_robin(catalogs):
        doc["year"] = doc_year(doc)
        if doc["year"] is not None and doc["year"] <= args.max_year:
            yield doc


def load_seen(path: Path):
    ids, hashes = set(), set()
    if path.exists():
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    rec = json.loads(line)
                    ids.add(rec["id"])
                    hashes.add(rec.get("sha256"))
    hashes.discard(None)
    return ids, hashes


def fetch_pdf(client: StroyinfClient, doc: dict, pdf_dir: Path) -> tuple:
    """-> (путь, байты, sha256). Уже лежащий на диске файл не качается заново."""
    path = pdf_dir / f"{doc['id']}.pdf"
    if path.exists():
        data = path.read_bytes()
    else:
        data = client.get(doc["pdf_url"]).content
        if not data.startswith(b"%PDF"):
            raise RuntimeError("ответ не похож на PDF")
    return path, data, hashlib.sha256(data).hexdigest()


def run(client: StroyinfClient, args) -> int:
    out = Path(args.out)
    pdf_dir = out / "pdf"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    docs_path = out / "documents.jsonl"
    seen_ids, seen_hashes = load_seen(docs_path)
    saved = 0
    with open(docs_path, "a", encoding="utf-8") as fh:
        for doc in iter_candidates(client, args):
            if args.limit and len(seen_ids) >= args.limit:
                break
            if doc["id"] in seen_ids:
                continue
            try:
                path, data, sha = fetch_pdf(client, doc, pdf_dir)
            except (requests.RequestException, RuntimeError) as exc:
                print(f"  пропуск {doc['designation']}: {exc}", file=sys.stderr)
                continue
            if sha in seen_hashes:
                print(f"  дубль {doc['designation']} (sha256 уже есть), пропуск")
                path.unlink(missing_ok=True)
                continue
            if not path.exists():
                tmp = path.with_suffix(".pdf.part")
                tmp.write_bytes(data)
                tmp.replace(path)
            try:
                layer = diagnose_pdf(path)
            except (pdfium.PdfiumError, RuntimeError) as exc:
                layer = {"error": str(exc), "recommend": "ocr"}
            record = {**doc, "file": f"pdf/{path.name}", "sha256": sha, "layer": layer}
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
            fh.flush()
            seen_ids.add(doc["id"])
            seen_hashes.add(sha)
            saved += 1
            print(
                f"[{len(seen_ids)}] {doc['designation']} ({doc['year']}): "
                f"слой {layer.get('median_quality')} -> {layer['recommend']}",
                flush=True,
            )
    print(f"Готово: новых документов {saved}, всего {len(seen_ids)} в {out}")
    return saved


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", required=True, help="папка результата")
    parser.add_argument(
        "--group", action="append", help=f"группа каталога (по умолчанию {DEFAULT_GROUPS})"
    )
    parser.add_argument(
        "--limit", type=int, default=50, help="размер набора в документах (0 — без лимита)"
    )
    parser.add_argument("--max-year", type=int, default=1991, help="только документы до года")
    parser.add_argument("--delay", type=float, default=1.0, help="пауза между запросами, с")
    parser.add_argument("--user-agent", default=DEFAULT_USER_AGENT)
    args = parser.parse_args(argv)
    args.group = args.group or DEFAULT_GROUPS
    return args


def main(argv=None) -> None:
    args = parse_args(argv)
    session = requests.Session()
    session.headers["User-Agent"] = args.user_agent
    run(StroyinfClient(session, delay=args.delay), args)


if __name__ == "__main__":
    main()
