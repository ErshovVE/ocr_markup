import pytest

from backend.labels import load_alphabet, normalize_label, out_of_alphabet
from backend.pipeline import _finalize_line


def test_normalize_label_maps_typographic_variants():
    assert normalize_label("„Нормы” – “x” ‘y’ don’t") == '"Нормы" — "x" \'y\' don\'t'


def test_normalize_label_keeps_dictionary_symbols():
    text = "«ёлочки» — длинное - дефис \"прямые\" 'апостроф'"
    assert normalize_label(text) == text


def test_load_alphabet_one_symbol_per_line(tmp_path):
    path = tmp_path / "dict.txt"
    path.write_text("а\nб\r\n—\n\n", encoding="utf-8")
    assert load_alphabet(str(path)) == frozenset({"а", "б", "—", " "})


@pytest.mark.parametrize("content", ["", "\n\n", "аб\nв\n"])
def test_load_alphabet_rejects_bad_files(tmp_path, content):
    path = tmp_path / "dict.txt"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ValueError):
        load_alphabet(str(path))


def test_out_of_alphabet_lists_each_symbol_once():
    alphabet = frozenset("абв ")
    assert out_of_alphabet("а£б£ ©", alphabet) == ["£", "©"]
    assert out_of_alphabet("аб в", alphabet) == []


@pytest.mark.parametrize(
    "bucket, text, normalize, alphabet, expected",
    [
        ("good", "„а”", False, None, ("good", "„а”")),
        ("good", "„а”", True, None, ("good", '"а"')),
        # нормализация до проверки: „ ” становятся " — в словаре
        ("good", "„а”", True, frozenset('а"'), ("good", '"а"')),
        ("good", "а£", True, frozenset("а"), ("needs_review", "а£")),
        # needs_review остаётся needs_review
        ("needs_review", "а", False, frozenset("а"), ("needs_review", "а")),
    ],
)
def test_finalize_line(bucket, text, normalize, alphabet, expected):
    assert _finalize_line(bucket, text, normalize, alphabet) == expected
