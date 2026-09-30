"""scripts/scrape/commons.py без сети: API Commons подменяется фейковой сессией."""

import importlib.util
import json
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "scrape" / "commons.py"


def _load():
    spec = importlib.util.spec_from_file_location("commons", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


commons = _load()


def _page(title, sha1, mime="image/jpeg", width=1000, license="CC BY-SA 4.0"):
    return {
        "title": title,
        "imageinfo": [
            {
                "url": f"https://upload.example/{sha1}.jpg",
                "thumburl": f"https://upload.example/thumb/{sha1}.jpg",
                "descriptionurl": f"https://commons.example/{title}",
                "width": width,
                "height": 800,
                "thumbwidth": min(width, 2000),
                "thumbheight": 400,
                "mime": mime,
                "sha1": sha1,
                "extmetadata": {
                    "LicenseShortName": {"value": license},
                    "Artist": {"value": '<a href="x">Иван &amp; Co</a>'},
                },
            }
        ],
    }


class FakeResponse:
    def __init__(self, payload=None, content=b"img"):
        self.payload = payload
        self.content = content
        self.status_code = 200
        self.headers = {}

    def json(self):
        return self.payload

    def raise_for_status(self):
        pass

    def iter_content(self, chunk_size):
        yield self.content


class FakeSession:
    """Отвечает на запросы API по (gcmtitle|cmtitle|gsrsearch, continue)."""

    def __init__(self, routes):
        self.routes = routes
        self.downloads = []

    def get(self, url, params=None, stream=False, timeout=None):
        if params is None:
            self.downloads.append(url)
            return FakeResponse()
        key = params.get("gcmtitle") or params.get("cmtitle") or params.get("gsrsearch")
        key = (key, params.get("list", "files"), params.get("gcmcontinue"))
        return FakeResponse(self.routes[key])


def _args(tmp_path, **kw):
    argv = ["--out", str(tmp_path), "--delay", "0"]
    for name, value in kw.items():
        flag = "--" + name.replace("_", "-")
        for v in value if isinstance(value, list) else [value]:
            argv += [flag, str(v)]
    return commons.parse_args(argv)


def _routes():
    root, sub = "Category:Handwriting", "Category:Letters"
    return {
        (root, "categorymembers", None): {"query": {"categorymembers": [{"title": sub}]}},
        (sub, "categorymembers", None): {"query": {"categorymembers": [{"title": root}]}},
        (root, "files", None): {
            "continue": {"gcmcontinue": "p2", "continue": "gcmcontinue||"},
            "query": {
                "pages": [
                    _page("File:A: b?.jpg", "aaaa1111"),
                    _page("File:vec.svg", "s1", "image/svg+xml"),
                ]
            },
        },
        (root, "files", "p2"): {
            "query": {"pages": [_page("File:Big.tif", "bbbb2222", "image/tiff", width=5000)]}
        },
        (sub, "files", None): {
            "query": {
                "pages": [
                    _page("File:Dup.jpg", "aaaa1111"),  # тот же sha1, другой title
                    _page("File:Small.jpg", "cccc3333", width=100),
                    _page("File:Other.jpg", "dddd4444", license="Public domain"),
                ]
            }
        },
    }


def test_crawls_subcategories_pages_and_filters(tmp_path):
    session = FakeSession(_routes())
    client = commons.CommonsClient(session, delay=0)
    saved = commons.run(client, _args(tmp_path, category="Handwriting", depth=2))

    assert saved == 3  # A, Big (tif через миниатюру), Other; svg/дубль/маленькая — нет
    assert "https://upload.example/thumb/bbbb2222.jpg" in session.downloads
    records = [
        json.loads(line)
        for line in (tmp_path / "metadata.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [r["title"] for r in records] == ["File:A: b?.jpg", "File:Big.tif", "File:Other.jpg"]
    assert records[0]["artist"] == "Иван & Co"
    assert records[0]["file"] == "images/aaaa1111_A__b.jpg"
    for rec in records:
        assert (tmp_path / rec["file"]).exists()
    rec_lines = (tmp_path / "rec.txt").read_text(encoding="utf-8").splitlines()
    assert rec_lines[0] == "images/aaaa1111_A__b.jpg\t"


def test_resume_skips_downloaded_and_respects_limit_and_license(tmp_path):
    routes = _routes()
    first = commons.CommonsClient(FakeSession(routes), 0)
    commons.run(first, _args(tmp_path, category="Handwriting", limit=1))
    session = FakeSession(routes)
    saved = commons.run(
        commons.CommonsClient(session, 0),
        _args(tmp_path, category="Handwriting", depth=1, license_regex="^Public domain"),
    )
    assert saved == 1
    assert session.downloads == ["https://upload.example/dddd4444.jpg"]


def test_safe_filename_is_windows_safe():
    name = commons.safe_filename('File:Письмо: "1905" / лист*1.jpeg', "0123456789", ".jpg")
    assert name == "01234567_Письмо___1905____лист_1.jpg"
    assert not any(ch in name for ch in '<>:"/\\|?*')
