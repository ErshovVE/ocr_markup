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

    bucket, text, engine, diverged = vote(
        results, threshold=0.6, preferred_model="tesseract", min_agree=1
    )

    assert bucket == "good"
    assert text == "c"
    assert engine == "tesseract"


def test_vote_ignores_preferred_model_below_threshold_and_falls_back_to_best_score():
    results = {
        "paddle": ("a", 0.5),
        "surya": ("b", 0.95),
        "tesseract": ("c", 0.4),
    }

    bucket, text, engine, diverged = vote(
        results, threshold=0.9, preferred_model="paddle", min_agree=1
    )

    assert bucket == "good"
    assert text == "b"
    assert engine == "surya"


def test_vote_returns_needs_review_when_best_score_below_threshold():
    results = {
        "paddle": ("a", 0.5),
        "surya": ("b", 0.4),
    }

    bucket, text, engine, diverged = vote(results, threshold=0.9, min_agree=1)

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

    bucket, text, engine, diverged = vote(results, threshold=0.9, min_agree=1)

    assert bucket == "good"
    assert diverged is True


def test_vote_not_diverged_when_only_one_engine_is_confident():
    results = {
        "paddle": ("вариант1", 0.95),
        "surya": ("вариант2", 0.3),
        "tesseract": ("вариант3", 0.1),
    }

    bucket, text, engine, diverged = vote(results, threshold=0.9, min_agree=1)

    assert bucket == "good"
    assert diverged is False


def test_vote_strict_two_of_three_sends_confident_disagreement_to_review():
    """C.10: при min_agree=2 без посимвольного совпадения 2 движков — только
    needs_review, даже если отдельные движки уверены."""
    results = {
        "paddle": ("Иванов", 0.97),
        "surya": ("Иваное", 0.96),
        "tesseract": ("", 0.0),
    }

    bucket, text, engine, diverged = vote(results, threshold=0.9, min_agree=2)

    assert bucket == "needs_review"
    assert (text, engine) == ("Иванов", "paddle")
    assert diverged is True


def test_vote_strict_single_confident_engine_is_not_enough():
    results = {
        "paddle": ("Иванов", 0.97),
        "surya": ("Ивонов", 0.60),
        "tesseract": ("Ивaнов", 0.40),  # латинская "a" — не совпадение
    }

    bucket, _, _, _ = vote(results, threshold=0.9, min_agree=2)

    assert bucket == "needs_review"


def test_vote_strict_hint_prefers_preferred_model_text():
    results = {"paddle": ("a", 0.97), "surya": ("b", 0.5)}

    bucket, text, engine, _ = vote(results, threshold=0.9, preferred_model="surya", min_agree=2)

    assert (bucket, text, engine) == ("needs_review", "b", "surya")


def test_vote_with_key_agrees_ignoring_spaces():
    from backend.text_keys import no_spaces_key

    results = {
        "custom": ("2.5.1", 0.9),
        "surya": ("2 .5 .1", 0.8),
        "vlm_line": ("2.8.1", 1.0),
    }

    bucket, text, engine, diverged = vote(results, threshold=0.5, key=no_spaces_key)

    assert (bucket, text, engine) == ("good", "2.5.1", "custom")
    assert diverged is True


def test_vote_with_key_returns_preferred_text_from_winning_group():
    from backend.text_keys import no_spaces_key

    results = {"custom": ("2.5.1", 0.9), "surya": ("2 .5 .1", 0.8)}

    bucket, text, engine, _ = vote(
        results, threshold=0.5, preferred_model="surya", key=no_spaces_key
    )

    assert (bucket, text, engine) == ("good", "2 .5 .1", "surya")


def test_vote_with_key_ignores_preferred_outside_winning_group():
    from backend.text_keys import no_spaces_key

    results = {"custom": ("abc", 0.9), "surya": ("a bc", 0.8), "vlm_line": ("xyz", 1.0)}

    _, text, engine, _ = vote(results, threshold=0.5, preferred_model="vlm_line", key=no_spaces_key)

    assert (text, engine) == ("abc", "custom")


def test_vote_without_key_still_exact():
    results = {"custom": ("2.5.1", 0.9), "surya": ("2 .5 .1", 0.8)}

    bucket, _, _, diverged = vote(results, threshold=0.5)

    assert bucket == "needs_review"
    assert diverged is True


def test_vote_with_key_not_diverged_when_keys_equal():
    from backend.text_keys import no_spaces_key

    results = {"custom": ("2.5.1", 0.9), "surya": ("2 .5 .1", 0.8)}

    assert vote(results, threshold=0.5, key=no_spaces_key)[3] is False
