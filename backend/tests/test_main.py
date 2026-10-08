"""API-тесты backend/main.py (pipeline/job замоканы через backend.jobs)."""

import importlib
import os

import pytest
from fastapi.testclient import TestClient

from backend import main


@pytest.fixture
def client(monkeypatch):
    # Не даём _readiness_warnings ходить в сеть/subprocess.
    monkeypatch.setattr(main.models_status, "get_status", lambda include_vlm=True: {})
    return TestClient(main.app)


@pytest.fixture
def input_dir(tmp_path):
    d = tmp_path / "docs"
    d.mkdir()
    return str(d)


def test_run_rejects_missing_input_dir(client, tmp_path):
    r = client.post(
        "/run", json={"input_dir": str(tmp_path / "nope"), "output_dir": str(tmp_path / "o")}
    )
    assert r.status_code == 400


def test_run_validates_score_threshold_range(client, input_dir, tmp_path):
    r = client.post(
        "/run",
        json={"input_dir": input_dir, "output_dir": str(tmp_path / "o"), "score_threshold": 2.0},
    )
    assert r.status_code == 422


@pytest.mark.parametrize(
    "payload_extra",
    [
        {"detector_engine": "bogus"},
        {"lang": "de"},
        {"mode": "vlm", "vlm_engines": []},
        {"mode": "vlm", "vlm_engines": ["not_a_model"]},
        {"engines": ["paddle", "surya"], "min_agree": 1, "preferred_model": "tesseract"},
        {"engines": ["paddle"], "min_agree": 5},
        {"iou_threshold": 0.0},
        {"extract_pdf_text_layer": False, "pdf_ocr_fallback": False},
    ],
)
def test_run_rejects_bad_cross_field_combos(client, input_dir, tmp_path, payload_extra):
    body = {"input_dir": input_dir, "output_dir": str(tmp_path / "o")}
    body.update(payload_extra)
    assert client.post("/run", json=body).status_code == 422


def test_run_rejects_unwritable_output_dir(client, input_dir):
    # файл вместо каталога → os.makedirs упадёт
    bad_out = os.path.join(input_dir, "not_a_dir.txt")
    open(bad_out, "w").close()
    r = client.post("/run", json={"input_dir": input_dir, "output_dir": os.path.join(bad_out, "x")})
    assert r.status_code == 400


def test_run_starts_job_and_returns_warnings(client, input_dir, tmp_path, monkeypatch):
    monkeypatch.setattr(main, "start_job", lambda *a, **k: "job-123")
    r = client.post("/run", json={"input_dir": input_dir, "output_dir": str(tmp_path / "o")})
    assert r.status_code == 200
    assert r.json() == {"job_id": "job-123", "warnings": []}


@pytest.mark.parametrize(
    "payload_extra, expected", [({}, False), ({"append_crop_size": True}, True)]
)
def test_run_passes_append_crop_size_to_job(
    client, input_dir, tmp_path, monkeypatch, payload_extra, expected
):
    seen = {}

    def fake_start_job(*a, **k):
        seen.update(k)
        return "job-1"

    monkeypatch.setattr(main, "start_job", fake_start_job)
    payload = {"input_dir": input_dir, "output_dir": str(tmp_path / "o"), **payload_extra}
    r = client.post("/run", json=payload)
    assert r.status_code == 200
    assert seen["append_crop_size"] is expected


def test_run_conflict_when_job_already_active(client, input_dir, tmp_path, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("Уже выполняется задание x")

    monkeypatch.setattr(main, "start_job", boom)
    r = client.post("/run", json={"input_dir": input_dir, "output_dir": str(tmp_path / "o")})
    assert r.status_code == 409


def test_result_returns_409_while_running_and_404_when_unknown(client, monkeypatch):
    class _Job:
        status = "running"
        result = None

    monkeypatch.setattr(main, "get_job", lambda jid: _Job() if jid == "run" else None)
    assert client.get("/result/run").status_code == 409
    assert client.get("/result/unknown").status_code == 404


def test_status_snapshot_404_when_missing(client, tmp_path):
    r = client.get("/jobs/status_snapshot", params={"output_dir": str(tmp_path)})
    assert r.status_code == 404


def test_data_root_guard_rejects_paths_outside_root(tmp_path, monkeypatch):
    root = tmp_path / "data"
    root.mkdir()
    (root / "in").mkdir()
    monkeypatch.setenv("OCR_DATA_ROOT", str(root))
    reloaded = importlib.reload(main)
    monkeypatch.setattr(reloaded.models_status, "get_status", lambda include_vlm=True: {})
    monkeypatch.setattr(reloaded, "start_job", lambda *a, **k: "j")
    c = TestClient(reloaded.app)
    outside = tmp_path / "elsewhere"
    outside.mkdir()

    assert (
        c.post(
            "/run", json={"input_dir": str(outside), "output_dir": str(root / "out")}
        ).status_code
        == 400
    )
    assert (
        c.post(
            "/run", json={"input_dir": str(root / "in"), "output_dir": str(root / "out")}
        ).status_code
        == 200
    )
    # вернуть модуль в исходное состояние для остальных тестов
    monkeypatch.delenv("OCR_DATA_ROOT", raising=False)
    importlib.reload(main)


def _capture_start_job(monkeypatch):
    seen = {}

    def fake_start_job(*a, **k):
        seen.update(k)
        return "job-1"

    monkeypatch.setattr(main, "start_job", fake_start_job)
    return seen


def test_run_passes_normalize_labels_and_loaded_alphabet(client, input_dir, tmp_path, monkeypatch):
    seen = _capture_start_job(monkeypatch)
    alphabet = tmp_path / "dict.txt"
    alphabet.write_text("а\nб\n", encoding="utf-8")
    payload = {
        "input_dir": input_dir,
        "output_dir": str(tmp_path / "o"),
        "normalize_labels": True,
        "alphabet_file": str(alphabet),
    }
    assert client.post("/run", json=payload).status_code == 200
    assert seen["normalize_labels"] is True
    assert seen["alphabet"] == frozenset("аб ")


def test_run_without_alphabet_passes_none(client, input_dir, tmp_path, monkeypatch):
    seen = _capture_start_job(monkeypatch)
    payload = {"input_dir": input_dir, "output_dir": str(tmp_path / "o")}
    assert client.post("/run", json=payload).status_code == 200
    assert seen["normalize_labels"] is False and seen["alphabet"] is None


@pytest.mark.parametrize("content", [None, "аб\n"])
def test_run_rejects_missing_or_bad_alphabet(client, input_dir, tmp_path, monkeypatch, content):
    _capture_start_job(monkeypatch)
    alphabet = tmp_path / "dict.txt"
    if content is not None:
        alphabet.write_text(content, encoding="utf-8")
    payload = {
        "input_dir": input_dir,
        "output_dir": str(tmp_path / "o"),
        "alphabet_file": str(alphabet),
    }
    response = client.post("/run", json=payload)
    assert response.status_code == 400
    assert "alphabet_file" in response.json()["detail"]


@pytest.fixture
def label_file(tmp_path):
    path = tmp_path / "labels.txt"
    path.write_text("crops/0/a.png\tметка\n", encoding="utf-8")
    return str(path)


@pytest.fixture
def model_dir(tmp_path):
    d = tmp_path / "model"
    d.mkdir()
    (d / "inference.yml").write_text("Global: {}\n", encoding="utf-8")
    return str(d)


@pytest.mark.parametrize(
    "payload_extra",
    [
        {"mode": "crops"},
        {"engines": ["custom", "surya"]},
        {"engines": ["vlm_line", "surya"]},
        {"engines": ["vlm_line", "surya"], "line_vlm_engine": "hunyuan_ocr"},
        {"engines": ["surya", "label"]},
        {"label_votes": True},
        {"vote_key": "bogus"},
        {"mode": "crops", "label_file": "x", "engines": ["surya"], "min_agree": 2},
        {"mode": "crops", "label_file": "x", "degrade_page_share": 0.5},
    ],
)
def test_run_rejects_bad_crops_and_engine_combos(client, input_dir, tmp_path, payload_extra):
    body = {"input_dir": input_dir, "output_dir": str(tmp_path / "o"), **payload_extra}
    assert client.post("/run", json=body).status_code == 422


def test_run_crops_label_votes_allows_min_agree_above_engines(
    client, input_dir, tmp_path, monkeypatch, label_file
):
    _capture_start_job(monkeypatch)
    body = {
        "input_dir": input_dir,
        "output_dir": str(tmp_path / "o"),
        "mode": "crops",
        "label_file": label_file,
        "engines": ["surya"],
        "min_agree": 2,
        "label_votes": True,
    }
    assert client.post("/run", json=body).status_code == 200


def test_run_crops_rejects_missing_label_file(client, input_dir, tmp_path, monkeypatch):
    _capture_start_job(monkeypatch)
    body = {
        "input_dir": input_dir,
        "output_dir": str(tmp_path / "o"),
        "mode": "crops",
        "label_file": str(tmp_path / "nope.txt"),
    }
    response = client.post("/run", json=body)
    assert response.status_code == 400
    assert "label_file" in response.json()["detail"]


def test_run_custom_requires_inference_yml(client, input_dir, tmp_path, monkeypatch):
    _capture_start_job(monkeypatch)
    empty_dir = tmp_path / "empty_model"
    empty_dir.mkdir()
    body = {
        "input_dir": input_dir,
        "output_dir": str(tmp_path / "o"),
        "engines": ["custom", "surya"],
        "custom_model_dir": str(empty_dir),
    }
    response = client.post("/run", json=body)
    assert response.status_code == 400
    assert "inference.yml" in response.json()["detail"]


def test_run_passes_crops_fields_to_job(
    client, input_dir, tmp_path, monkeypatch, label_file, model_dir
):
    seen = _capture_start_job(monkeypatch)
    body = {
        "input_dir": input_dir,
        "output_dir": str(tmp_path / "o"),
        "mode": "crops",
        "label_file": label_file,
        "engines": ["custom", "surya", "vlm_line"],
        "min_agree": 2,
        "custom_model_dir": model_dir,
        "line_vlm_engine": "glm_ocr",
        "vote_key": "no_spaces",
        "label_votes": True,
    }
    assert client.post("/run", json=body).status_code == 200
    assert seen["label_file"] == label_file
    assert seen["label_votes"] is True
    options = seen["options"]
    assert (options.custom_model_dir, options.line_vlm_engine, options.vote_key) == (
        model_dir,
        "glm_ocr",
        "no_spaces",
    )


def test_run_vlm_line_readiness_warning(client, input_dir, tmp_path, monkeypatch):
    class _State:
        status = "error"
        detail = "нет ответа"

    calls = []

    def fake_status(include_vlm=True):
        calls.append(include_vlm)
        return {"vlm_glm_ocr": _State()}

    monkeypatch.setattr(main.models_status, "get_status", fake_status)
    _capture_start_job(monkeypatch)
    body = {
        "input_dir": input_dir,
        "output_dir": str(tmp_path / "o"),
        "engines": ["vlm_line", "surya"],
        "line_vlm_engine": "glm_ocr",
    }
    response = client.post("/run", json=body)
    assert response.status_code == 200
    assert calls == [True]
    assert any("glm_ocr" in w for w in response.json()["warnings"])


def test_default_engines_unchanged(client, input_dir, tmp_path, monkeypatch):
    import inspect

    seen = {}

    def fake_start_job(*a, **k):
        # по имени параметра, а не по позиции — переживёт перестановку аргументов
        seen.update(inspect.signature(main.jobs.start_job).bind(*a, **k).arguments)
        return "job-1"

    monkeypatch.setattr(main, "start_job", fake_start_job)
    body = {"input_dir": input_dir, "output_dir": str(tmp_path / "o")}
    assert client.post("/run", json=body).status_code == 200
    assert seen["engines"] == ["paddle", "surya", "tesseract"]
