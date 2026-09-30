"""Скачивает изображения с Wikimedia Commons (категории и/или поиск) для OCR-датасета.

    python scripts/scrape/commons.py --out data/commons ^
        --category "Handwritten letters" --depth 1 ^
        --search "рукопись письмо" --limit 500 ^
        --user-agent "ocr-markup-scraper/1.0 (you@example.com)"

Результат в --out:
  images/        — сами картинки (jpg/png), имена безопасны для Windows;
  metadata.jsonl — по строке на файл: title, страница, url, лицензия, автор,
                   описание, sha1, категории-источники;
  rec.txt        — "images/<файл>\\t" (пустой текст) — сразу открывается
                   в ручной разметке; папку images/ можно отдавать и в
                   авторазметку backend'а как input_dir.

Повторный запуск докачивает: файлы, уже записанные в metadata.jsonl (по
title и sha1), пропускаются.

Правила Wikimedia (https://meta.wikimedia.org/wiki/User-Agent_policy): в
User-Agent нужен контакт; запросы последовательные, с maxlag. На Commons только
свободные лицензии, но условия у них разные (CC BY / BY-SA требуют указания
автора) — лицензия и автор каждого файла сохраняются в metadata.jsonl;
--license-regex отсекает лишнее (например "^(CC0|Public domain|PD)").

Нужен только пакет requests.
"""

import argparse
import html
import json
import re
import sys
import time
from collections import deque
from pathlib import Path

import requests

API_URL = "https://commons.wikimedia.org/w/api.php"
DEFAULT_USER_AGENT = "ocr-markup-commons-scraper/1.0 (https://github.com/ErshovVE/ocr_markup)"

# Растровые форматы, пригодные для OCR. SVG/GIF/PDF/DjVu пропускаем:
# векторные и анимированные картинки не нужны, многостраничные — отдельная история.
ALLOWED_MIMES = {"image/jpeg", "image/png", "image/tiff", "image/webp"}
# Эти форматы качаем только через миниатюру (Commons отдаёт её в jpg/png).
THUMB_ONLY_MIMES = {"image/tiff", "image/webp"}

EXTMETADATA_FIELDS = (
    "LicenseShortName|LicenseUrl|Artist|ImageDescription|UsageTerms|DateTimeOriginal"
)
BATCH = 50  # максимум generator'а для обычных (не bot) аккаунтов
MAX_RETRIES = 5

_WINDOWS_BAD = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_TAG = re.compile(r"<[^>]+>")
_YEAR = re.compile(r"(?<!\d)(1[0-9]{3}|20[0-9]{2})(?!\d)")


def strip_html(value: str) -> str:
    """Artist/ImageDescription в extmetadata — HTML; оставляем чистый текст."""
    text = html.unescape(_TAG.sub(" ", value or ""))
    return " ".join(text.split())


def safe_filename(title: str, sha1: str, ext: str, max_len: int = 100) -> str:
    """'File:Письмо 1905.jpg' -> '<sha1[:8]>_Письмо_1905.jpg'.

    Префикс sha1 исключает коллизии после обрезки/замены символов."""
    stem = title.split(":", 1)[-1].rsplit(".", 1)[0]
    stem = _WINDOWS_BAD.sub("_", stem)
    stem = re.sub(r"\s+", "_", stem).strip("._") or "file"
    return f"{sha1[:8]}_{stem[:max_len]}{ext}"


def guess_year(record: dict):
    """Самый ранний год из даты, названия и описания файла.

    DateTimeOriginal часто — дата съёмки/скана, а не документа, поэтому одной
    ей не верим. Берём минимум: для отсева старых рукописей лучше лишний раз
    выбросить."""
    text = " ".join(record.get(k, "") or "" for k in ("date", "title", "description"))
    years = [int(y) for y in _YEAR.findall(text)]
    return min(years) if years else None


class CommonsClient:
    def __init__(self, session: requests.Session, delay: float = 0.5, api_url: str = API_URL):
        self.session = session
        self.delay = delay
        self.api_url = api_url

    def _get(self, url: str, **kwargs) -> requests.Response:
        for attempt in range(MAX_RETRIES):
            try:
                resp = self.session.get(url, timeout=60, **kwargs)
            except requests.RequestException as exc:
                wait = 2**attempt
                print(f"  сетевая ошибка ({exc}); повтор через {wait} с", file=sys.stderr)
                time.sleep(wait)
                continue
            if resp.status_code in (429, 500, 502, 503, 504):
                wait = int(resp.headers.get("Retry-After") or 2**attempt)
                print(f"  HTTP {resp.status_code}; повтор через {wait} с", file=sys.stderr)
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp
        raise RuntimeError(f"не удалось получить {url} за {MAX_RETRIES} попыток")

    def query(self, params: dict):
        """Итерирует ответы action=query, проходя по continue."""
        base = {"action": "query", "format": "json", "formatversion": "2", "maxlag": "5"}
        cont: dict = {}
        while True:
            for attempt in range(MAX_RETRIES):
                data = self._get(self.api_url, params={**base, **params, **cont}).json()
                error = data.get("error", {})
                if error.get("code") != "maxlag":
                    break
                time.sleep(5 * (attempt + 1))
            if "error" in data:
                raise RuntimeError(f"ошибка API: {data['error']}")
            yield data
            time.sleep(self.delay)
            if "continue" not in data:
                return
            cont = data["continue"]

    def subcategories(self, root: str, depth: int) -> list:
        """Категория root и её подкатегории до глубины depth (BFS, без повторов)."""
        root = _category_title(root)
        seen = {root}
        order = [root]
        queue = deque([(root, 0)])
        while queue:
            title, level = queue.popleft()
            if level >= depth:
                continue
            params = {
                "list": "categorymembers",
                "cmtitle": title,
                "cmtype": "subcat",
                "cmlimit": "500",
            }
            for data in self.query(params):
                for member in data.get("query", {}).get("categorymembers", []):
                    sub = member["title"]
                    if sub not in seen:
                        seen.add(sub)
                        order.append(sub)
                        queue.append((sub, level + 1))
        return order

    def _files(self, generator_params: dict, max_width: int):
        params = {
            **generator_params,
            "prop": "imageinfo",
            "iiprop": "url|size|mime|sha1|extmetadata",
            "iiextmetadatafilter": EXTMETADATA_FIELDS,
            "iiurlwidth": str(max_width),
        }
        for data in self.query(params):
            for page in data.get("query", {}).get("pages", []):
                if page.get("imageinfo"):
                    yield page

    def category_files(self, category: str, max_width: int):
        return self._files(
            {
                "generator": "categorymembers",
                "gcmtitle": _category_title(category),
                "gcmtype": "file",
                "gcmlimit": str(BATCH),
            },
            max_width,
        )

    def search_files(self, text: str, max_width: int):
        return self._files(
            {
                "generator": "search",
                "gsrsearch": text,
                "gsrnamespace": "6",  # File:
                "gsrlimit": str(BATCH),
            },
            max_width,
        )

    def download(self, url: str, path: Path) -> None:
        resp = self._get(url, stream=True)
        tmp = path.with_suffix(path.suffix + ".part")
        with open(tmp, "wb") as fh:
            for chunk in resp.iter_content(chunk_size=1 << 16):
                fh.write(chunk)
        tmp.replace(path)
        time.sleep(self.delay)


def _category_title(name: str) -> str:
    name = name.strip().replace("_", " ")
    return name if name.startswith("Category:") else f"Category:{name}"


def to_record(page: dict, source: str, max_width: int):
    """Страница API -> (url для скачивания, запись metadata) или (None, причина)."""
    info = page["imageinfo"][0]
    mime = info.get("mime", "")
    if mime not in ALLOWED_MIMES:
        return None, f"формат {mime}"
    use_thumb = mime in THUMB_ONLY_MIMES or info.get("width", 0) > max_width
    url = info.get("thumburl") if use_thumb else info.get("url")
    if not url:
        return None, "нет url"
    meta = info.get("extmetadata", {})

    def field(name):
        return strip_html(meta.get(name, {}).get("value", ""))

    record = {
        "title": page["title"],
        "page_url": info.get("descriptionurl", ""),
        "download_url": url,
        "width": info.get("thumbwidth") if use_thumb else info.get("width"),
        "height": info.get("thumbheight") if use_thumb else info.get("height"),
        "mime": mime,
        "sha1": info.get("sha1", ""),
        "license": field("LicenseShortName") or field("UsageTerms"),
        "license_url": field("LicenseUrl"),
        "artist": field("Artist"),
        "description": field("ImageDescription"),
        "date": field("DateTimeOriginal"),
        "source": source,
    }
    record["year"] = guess_year(record)
    return url, record


def load_seen(metadata_path: Path):
    titles, hashes = set(), set()
    if metadata_path.exists():
        with open(metadata_path, encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    rec = json.loads(line)
                    titles.add(rec["title"])
                    if rec.get("sha1"):
                        hashes.add(rec["sha1"])
    return titles, hashes


def iter_sources(client: CommonsClient, args):
    for category in args.category:
        for cat in client.subcategories(category, args.depth):
            print(f"== {cat}", flush=True)
            for page in client.category_files(cat, args.max_width):
                yield cat, page
    for text in args.search:
        print(f"== поиск: {text}", flush=True)
        for page in client.search_files(text, args.max_width):
            yield f"search:{text}", page


def run(client: CommonsClient, args) -> int:
    out = Path(args.out)
    images = out / "images"
    images.mkdir(parents=True, exist_ok=True)
    metadata_path = out / "metadata.jsonl"
    seen_titles, seen_hashes = load_seen(metadata_path)
    license_re = re.compile(args.license_regex, re.IGNORECASE) if args.license_regex else None

    saved = 0
    with (
        open(metadata_path, "a", encoding="utf-8") as meta_fh,
        open(out / "rec.txt", "a", encoding="utf-8") as rec_fh,
    ):
        for source, page in iter_sources(client, args):
            if page["title"] in seen_titles:
                continue
            url, record = to_record(page, source, args.max_width)
            if url is None:
                continue
            if record["sha1"] and record["sha1"] in seen_hashes:
                continue
            if (record["width"] or 0) < args.min_width:
                continue
            if license_re and not license_re.search(record["license"]):
                continue
            if args.min_year and record["year"] is not None and record["year"] < args.min_year:
                continue

            ext = Path(url.split("?", 1)[0]).suffix.lower() or ".jpg"
            name = safe_filename(record["title"], record["sha1"] or "00000000", ext)
            try:
                client.download(url, images / name)
            except (requests.RequestException, RuntimeError) as exc:
                print(f"  пропуск {record['title']}: {exc}", file=sys.stderr)
                continue

            record["file"] = f"images/{name}"
            meta_fh.write(json.dumps(record, ensure_ascii=False) + "\n")
            rec_fh.write(f"images/{name}\t\n")
            meta_fh.flush()
            rec_fh.flush()
            seen_titles.add(record["title"])
            seen_hashes.add(record["sha1"])
            saved += 1
            print(f"  [{saved}] {name} ({record['license']})", flush=True)
            if args.limit and saved >= args.limit:
                break
    print(f"Готово: скачано {saved} файлов в {images}")
    return saved


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", required=True, help="папка результата")
    parser.add_argument(
        "--category", action="append", default=[], help="категория Commons (можно несколько раз)"
    )
    parser.add_argument(
        "--depth", type=int, default=0, help="глубина обхода подкатегорий (0 — только сама)"
    )
    parser.add_argument(
        "--search",
        action="append",
        default=[],
        help="полнотекстовый поиск по файлам (можно несколько раз)",
    )
    parser.add_argument("--limit", type=int, default=0, help="максимум файлов (0 — без лимита)")
    parser.add_argument(
        "--max-width",
        type=int,
        default=2000,
        help="шире — качается миниатюра этой ширины (экономит трафик)",
    )
    parser.add_argument("--min-width", type=int, default=600, help="уже — пропускаем")
    parser.add_argument("--license-regex", default="", help="фильтр по LicenseShortName")
    parser.add_argument(
        "--min-year",
        type=int,
        default=0,
        help="пропускать файлы с годом раньше этого (1918 — без дореформенной орфографии);"
        " файлы без распознанного года остаются",
    )
    parser.add_argument("--delay", type=float, default=0.5, help="пауза между запросами, с")
    parser.add_argument(
        "--user-agent",
        default=DEFAULT_USER_AGENT,
        help="User-Agent с контактом (требование Wikimedia)",
    )
    args = parser.parse_args(argv)
    if not args.category and not args.search:
        parser.error("нужен хотя бы один --category или --search")
    return args


def main(argv=None) -> None:
    args = parse_args(argv)
    session = requests.Session()
    session.headers["User-Agent"] = args.user_agent
    run(CommonsClient(session, delay=args.delay), args)


if __name__ == "__main__":
    main()
