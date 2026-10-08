import pytest

from backend.text_keys import VOTE_KEYS, no_spaces_key, normalized_key, vote_key


def test_no_spaces_key_merges_split_words():
    assert no_spaces_key("п р и я ти я") == no_spaces_key("приятия")
    assert no_spaces_key("2 .5 .1") == no_spaces_key("2.5.1")


def test_normalized_key_typography():
    assert normalized_key("а – б") == normalized_key("а — б")
    assert normalized_key("„текст”") == normalized_key('"текст"')


def test_normalized_key_collapses_spaces_and_yo():
    assert normalized_key("  ещё   раз ") == "еще раз"
    assert normalized_key("Ёлка") == normalized_key("Елка")


def test_normalized_key_keeps_spaces_between_words():
    assert normalized_key("при ятия") != normalized_key("приятия")


def test_vote_key_exact_is_none_and_others_callable():
    assert vote_key("exact") is None
    assert vote_key("normalized") is normalized_key
    assert vote_key("no_spaces") is no_spaces_key
    assert set(VOTE_KEYS) == {"exact", "normalized", "no_spaces"}


def test_vote_key_unknown_raises():
    with pytest.raises(ValueError):
        vote_key("bogus")
