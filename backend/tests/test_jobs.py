import time

import pytest

from backend import jobs


@pytest.fixture(autouse=True)
def _reset_job_registry():
    jobs._jobs.clear()
    jobs._active_job_id = None
    yield
    jobs._jobs.clear()
    jobs._active_job_id = None


def _fake_pipeline_run(n_files=3, sleep_s=0.0, n_errors=0):
    def fake_run(
        input_dir,
        output_dir,
        threshold,
        preferred_model,
        lang,
        latin_model_size,
        extract_pdf_text_layer,
        detector_engine,
        engines=None,
        min_agree=None,
        on_found=None,
        on_file_done=None,
        on_line_done=None,
        on_error=None,
        should_cancel=None,
    ):
        if on_found:
            on_found(n_files)
        for i in range(n_errors):
            if on_error:
                on_error(f"error {i}")
        processed = 0
        for _ in range(n_files):
            if should_cancel and should_cancel():
                break
            time.sleep(sleep_s)
            if on_line_done:
                on_line_done("good", False)
            if on_file_done:
                on_file_done()
            processed += 1
        return processed, 0

    return fake_run


def _wait_until_finished(job_id, timeout=2.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = jobs.get_job(job_id)
        if job.status != "running":
            return job
        time.sleep(0.01)
    raise TimeoutError("job did not finish in time")


def test_start_job_reports_done_with_counts(monkeypatch, tmp_path):
    monkeypatch.setattr(jobs.pipeline, "run", _fake_pipeline_run(n_files=3))

    job_id = jobs.start_job(str(tmp_path), str(tmp_path / "out"), 0.9)
    job = _wait_until_finished(job_id)

    assert job.status == "done"
    assert job.docs_found == 3
    assert job.good_count == 3
    assert jobs.get_active_job_id() is None


def test_start_job_rejects_concurrent_run(monkeypatch, tmp_path):
    monkeypatch.setattr(jobs.pipeline, "run", _fake_pipeline_run(n_files=5, sleep_s=0.05))
    jobs.start_job(str(tmp_path), str(tmp_path / "out"), 0.9)

    with pytest.raises(RuntimeError):
        jobs.start_job(str(tmp_path), str(tmp_path / "out2"), 0.9)


def test_errors_accumulate_count_but_cap_stored_list(monkeypatch, tmp_path):
    n_errors = jobs.MAX_STORED_ERRORS + 5
    monkeypatch.setattr(jobs.pipeline, "run", _fake_pipeline_run(n_files=0, n_errors=n_errors))

    job_id = jobs.start_job(str(tmp_path), str(tmp_path / "out"), 0.9)
    job = _wait_until_finished(job_id)

    assert job.error_count == n_errors
    assert len(job.errors) == jobs.MAX_STORED_ERRORS
    assert job.errors[0] == f"error {n_errors - jobs.MAX_STORED_ERRORS}"
    assert job.errors[-1] == f"error {n_errors - 1}"


def test_cancel_job_raises_for_unknown_job():
    with pytest.raises(KeyError):
        jobs.cancel_job("unknown-job-id")


def test_cancel_job_raises_when_job_not_running(monkeypatch, tmp_path):
    monkeypatch.setattr(jobs.pipeline, "run", _fake_pipeline_run(n_files=1))
    job_id = jobs.start_job(str(tmp_path), str(tmp_path / "out"), 0.9)
    _wait_until_finished(job_id)

    with pytest.raises(RuntimeError):
        jobs.cancel_job(job_id)


def test_cancel_job_stops_running_job_early(monkeypatch, tmp_path):
    monkeypatch.setattr(jobs.pipeline, "run", _fake_pipeline_run(n_files=50, sleep_s=0.02))
    job_id = jobs.start_job(str(tmp_path), str(tmp_path / "out"), 0.9)

    time.sleep(0.05)
    jobs.cancel_job(job_id)

    job = _wait_until_finished(job_id, timeout=3.0)
    assert job.status == "cancelled"
    assert job.docs_processed < 50


def test_write_snapshot_and_read_back(tmp_path):
    state = jobs.JobState(status="done", good_count=5, error_count=2, errors=["x"])

    jobs._write_snapshot(str(tmp_path), state)
    snapshot = jobs.get_status_snapshot(str(tmp_path))

    assert snapshot["status"] == "done"
    assert snapshot["good_count"] == 5
    assert snapshot["error_count"] == 2
    assert snapshot["errors"] == ["x"]


def test_get_status_snapshot_returns_none_when_missing(tmp_path):
    assert jobs.get_status_snapshot(str(tmp_path / "nope")) is None


def test_status_dict_returns_a_copy_of_errors_not_the_live_list():
    state = jobs.JobState(status="running", errors=["a", "b"])

    snapshot = jobs.status_dict(state)
    snapshot["errors"].append("mutated by caller")

    assert state.errors == ["a", "b"]
