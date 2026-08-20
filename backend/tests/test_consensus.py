from backend.consensus import vote


def test_vote_returns_needs_review_for_empty_results():
    bucket, text, engine, diverged = vote({}, threshold=0.9)

    assert bucket == "needs_review"
    assert text == ""
    assert engine == ""
    assert diverged is False


def test_vote_returns_good_when_majority_of_engines_agree():
    results = {
        "paddle": ("привет", 0.5),
        "surya": ("привет", 0.4),
        "tesseract": ("совсем другое", 0.9),
    }

    bucket, text, engine, diverged = vote(results, threshold=0.9)

    assert bucket == "good"
    assert text == "привет"
    assert engine in ("paddle", "surya")


def test_vote_uses_preferred_model_when_score_meets_threshold():
    results = {
        "paddle": ("a", 0.5),
        "surya": ("b", 0.6),
        "tesseract": ("c", 0.7),
    }

    bucket, text, engine, diverged = vote(results, threshold=0.6, preferred_model="tesseract")

    assert bucket == "good"
    assert text == "c"
    assert engine == "tesseract"


def test_vote_ignores_preferred_model_below_threshold_and_falls_back_to_best_score():
    results = {
        "paddle": ("a", 0.5),
        "surya": ("b", 0.95),
        "tesseract": ("c", 0.4),
    }

    bucket, text, engine, diverged = vote(results, threshold=0.9, preferred_model="paddle")

    assert bucket == "good"
    assert text == "b"
    assert engine == "surya"


def test_vote_returns_needs_review_when_best_score_below_threshold():
    results = {
        "paddle": ("a", 0.5),
        "surya": ("b", 0.4),
    }

    bucket, text, engine, diverged = vote(results, threshold=0.9)

    assert bucket == "needs_review"
    assert engine == "paddle"
    assert text == "a"
    assert diverged is False


def test_vote_flags_diverged_when_two_confident_engines_disagree():
    results = {
        "paddle": ("вариант1", 0.95),
        "surya": ("вариант2", 0.92),
        "tesseract": ("вариант3", 0.4),
    }

    bucket, text, engine, diverged = vote(results, threshold=0.9)

    assert bucket == "good"
    assert diverged is True


def test_vote_not_diverged_when_only_one_engine_is_confident():
    results = {
        "paddle": ("вариант1", 0.95),
        "surya": ("вариант2", 0.3),
        "tesseract": ("вариант3", 0.1),
    }

    bucket, text, engine, diverged = vote(results, threshold=0.9)

    assert bucket == "good"
    assert diverged is False
