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

    assert c.post(
        "/run", json={"input_dir": str(outside), "output_dir": str(root / "out")}
    ).status_code == 400
    assert c.post(
        "/run", json={"input_dir": str(root / "in"), "output_dir": str(root / "out")}
    ).status_code == 200
    # вернуть модуль в исходное состояние для остальных тестов
    monkeypatch.delenv("OCR_DATA_ROOT", raising=False)
    importlib.reload(main)
