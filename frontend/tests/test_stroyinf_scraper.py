"""scripts/scrape/stroyinf.py без сети: каталог подменяется фейковым клиентом."""

import importlib.util
import io
import json
from pathlib import Path

import pypdfium2 as pdfium

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "scrape" / "stroyinf.py"


def _load():
    spec = importlib.util.spec_from_file_location("stroyinf", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


stroyinf = _load()


def _row(doc_id, designation, date=""):
    return (
        f"<tr class='m3'><td align='left'>"
        f"<a href='https://files.stroyinf.ru/Data2/1/1/{doc_id}.pdf' target='_blank' "
        f"title='{designation}' class='a2'><img src='/image/file2.gif'></a>"
        f"<a href='https://files.stroyinf.ru/Index2/1/1/{doc_id}.htm' target='_blank' "
        f"title='{designation}'>{designation}</a></td>"
        f"<td align='left'>Название {doc_id}</td><td align='center'>{date}</td>"
        f"<td align='center'><span class='stat31'>Действует</span></td></tr>"
    )


def _pdf_bytes(pages=1):
    doc = pdfium.PdfDocument.new()
    for _ in range(pages):
        doc.new_page(595, 842)
    buf = io.BytesIO()
    doc.save(buf)
    doc.close()
    return buf.getvalue()


def test_parse_groups():
    page = "<a href='/list2/64472-0.htm'>РТМ</a> <a href='/list2/64378-0.htm'>ОСТ</a>"
    assert stroyinf.parse_groups(page) == {"РТМ": "64472", "ОСТ": "64378"}


def test_parse_catalog_row():
    (doc,) = stroyinf.parse_catalog(f"<table>{_row('4293781789', 'РТМ II-2-67')}</table>")
    assert doc["id"] == "4293781789"
    assert doc["designation"] == "РТМ II-2-67"
    assert doc["title"] == "Название 4293781789"
    assert doc["status"] == "Действует"
    assert doc["pdf_url"].endswith("4293781789.pdf")


def test_parse_catalog_skips_rows_without_pdf():
    assert stroyinf.parse_catalog("<tr class='m3'><td>x</td></tr>") == []


def test_decode_html_falls_back_to_cp1251():
    assert stroyinf.decode_html("ГОСТ".encode("cp1251")) == "ГОСТ"


def test_doc_year():
    assert stroyinf.doc_year({"date": "01.01.1999", "designation": "РТМ 3-72-70"}) == 1999
    assert stroyinf.doc_year({"date": "", "designation": "РТМ 3-72-70"}) == 1970
    assert stroyinf.doc_year({"date": "", "designation": "ГОСТ 2.309-2002"}) == 2002
    assert stroyinf.doc_year({"date": "", "designation": "РТМ ПНП"}) is None


def test_round_robin_interleaves_sources():
    assert list(stroyinf.round_robin([[1, 2, 3], ["a"], [10, 20]])) == [1, "a", 10, 2, 20, 3]


class FakeClient:
    """Каталог РТМ из четырёх документов; 4 — после 1991 года."""

    def __init__(self, files):
        self.files = files
        self.downloads = []

    def groups(self):
        return {"РТМ": "1"}

    def catalog(self, gid, group):
        rows = [("1", "РТМ 1-70"), ("2", "РТМ 2-80"), ("3", "РТМ 3-85"), ("4", "РТМ 4-99")]
        for doc in stroyinf.parse_catalog("".join(_row(i, d) for i, d in rows)):
            yield {**doc, "group": group}

    def get(self, url):
        self.downloads.append(url)
        return type("Resp", (), {"content": self.files[Path(url).stem]})()


def _run(tmp_path, client, limit=0):
    args = stroyinf.parse_args(["--out", str(tmp_path), "--group", "РТМ", "--limit", str(limit)])
    return stroyinf.run(client, args)


def test_run_skips_duplicates_by_sha256(tmp_path):
    same = _pdf_bytes(1)
    client = FakeClient({"1": same, "2": _pdf_bytes(2), "3": same})
    assert _run(tmp_path, client) == 2  # 3 — дубль 1 по sha256, 4 — после 1991
    records = [json.loads(line) for line in open(tmp_path / "documents.jsonl", encoding="utf-8")]
    assert [r["id"] for r in records] == ["1", "2"]
    assert all(r["group"] == "РТМ" and len(r["sha256"]) == 64 for r in records)
    assert records[0]["layer"]["recommend"] == "ocr"  # пустые страницы — слоя нет
    assert sorted(p.name for p in (tmp_path / "pdf").iterdir()) == ["1.pdf", "2.pdf"]


def test_run_resumes_without_redownloading(tmp_path):
    files = {"1": _pdf_bytes(1), "2": _pdf_bytes(2), "3": _pdf_bytes(3)}
    assert _run(tmp_path, FakeClient(files), limit=1) == 1
    client = FakeClient(files)
    assert _run(tmp_path, client, limit=3) == 2
    assert [Path(u).stem for u in client.downloads] == ["2", "3"]


def test_run_reuses_pdf_left_on_disk(tmp_path):
    (tmp_path / "pdf").mkdir()
    (tmp_path / "pdf" / "1.pdf").write_bytes(_pdf_bytes(1))
    client = FakeClient({"2": _pdf_bytes(2), "3": _pdf_bytes(3)})
    assert _run(tmp_path, client) == 3
    assert "1" not in [Path(u).stem for u in client.downloads]


def test_run_rejects_non_pdf_response(tmp_path):
    client = FakeClient({"1": b"<html>404</html>", "2": _pdf_bytes(2), "3": _pdf_bytes(3)})
    assert _run(tmp_path, client) == 2
    assert not (tmp_path / "pdf" / "1.pdf").exists()
