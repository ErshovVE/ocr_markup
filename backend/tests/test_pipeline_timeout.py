import time

from backend.pipeline import _run_engines_with_timeout


def test_run_engines_with_timeout_returns_all_results_within_timeout():
    def recognize(letter):
        return f"text-{letter}", 0.9

    results = _run_engines_with_timeout(
        {"a": (recognize, ("A",)), "b": (recognize, ("B",))},
        timeout=1.0,
        source_label="test",
    )

    assert results == {"a": ("text-A", 0.9), "b": ("text-B", 0.9)}


def test_run_engines_with_timeout_falls_back_to_empty_result_on_timeout():
    def slow():
        time.sleep(0.5)
        return "late", 0.9

    def fast():
        return "ok", 0.5

    errors = []
    results = _run_engines_with_timeout(
        {"slow": (slow, ()), "fast": (fast, ())},
        timeout=0.05,
        source_label="crop-1",
        on_error=errors.append,
    )

    assert results["fast"] == ("ok", 0.5)
    assert results["slow"] == ("", 0.0)
    assert len(errors) == 1
    assert "slow" in errors[0]
    assert "crop-1" in errors[0]


def test_run_engines_with_timeout_works_without_on_error_callback():
    def slow():
        time.sleep(0.3)
        return "late", 0.9

    results = _run_engines_with_timeout(
        {"slow": (slow, ())}, timeout=0.05, source_label="crop-2"
    )

    assert results["slow"] == ("", 0.0)


def test_run_engines_with_timeout_bounds_total_wait_when_multiple_engines_hang():
    def hang():
        time.sleep(2.0)
        return "late", 0.9

    started = time.monotonic()
    results = _run_engines_with_timeout(
        {"a": (hang, ()), "b": (hang, ()), "c": (hang, ())},
        timeout=0.1,
        source_label="crop-3",
    )
    elapsed = time.monotonic() - started

    assert results == {"a": ("", 0.0), "b": ("", 0.0), "c": ("", 0.0)}
    # Раньше .result(timeout=...) вызывался последовательно на каждый future,
    # так что суммарное ожидание могло вырасти до len(calls) * timeout. Общий
    # дедлайн держит это в районе timeout, а не 3x.
    assert elapsed < 0.3


def test_run_engines_with_timeout_does_not_degrade_after_a_hang():
    """Зависший вызов раньше навсегда отнимал воркера у общего пула — все
    последующие вызовы того же движка тоже начинали таймаутиться, даже если
    сами по себе выполнялись мгновенно. Один поток на вызов не должен иметь
    такого побочного эффекта: быстрый вызов после зависшего остаётся быстрым."""

    def hang():
        time.sleep(2.0)
        return "late", 0.9

    def fast():
        return "ok", 0.9

    for _ in range(5):
        _run_engines_with_timeout({"e": (hang, ())}, timeout=0.02, source_label="warmup")

    started = time.monotonic()
    results = _run_engines_with_timeout({"e": (fast, ())}, timeout=1.0, source_label="after")
    elapsed = time.monotonic() - started

    assert results == {"e": ("ok", 0.9)}
    assert elapsed < 0.2
