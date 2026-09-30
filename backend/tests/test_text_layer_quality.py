from backend import text_layer_quality as tlq

CLEAN = ["Настоящий", "стандарт", "распространяется", "на", "шайбы", "по", "ГОСТ", "4087-69"]
GARBAGE = ["ПРЖКТИРОВАБЕ", "КСНСТР/КЦИЙ", "BATCH", "Ур§", "б?'1", "PTU", "J", "2б?", "19В6"]


def test_word_ok_accepts_normal_words():
    words = ["Технические", "(ГОСТ", "3619-69,", "кгс/см2", "т/ч", "м3", "1.2.1.", "II", "«да»"]
    words += ["СССР.", "стан\x02дартизации", "т.п.),", "„Об", "стандартизации”,", "©"]
    assert all(tlq.word_ok(w) for w in words)


def test_word_ok_rejects_ocr_garbage():
    words = ["КСНСТР/КЦИЙ", "BATCH", "пр0ект", "Ур§", "ЖЩРТСК", "т�кст", "19В6"]
    assert not any(tlq.word_ok(w) for w in words)


def test_homoglyph_rule_only_for_cyrillic_text():
    assert not tlq.word_ok("copy", cyrillic_text=True)
    assert tlq.word_ok("copy", cyrillic_text=False)
    assert tlq.text_quality(["Please", "copy", "the", "page", "don't", "für"]) == 1.0


def test_text_quality():
    assert tlq.text_quality(["Изменение", "BATCH"]) == 9 / 14
    assert tlq.text_quality([]) == 0.0


def test_page_qualities_skips_short_pages():
    assert tlq.page_qualities([CLEAN, ["два", "слова"], []]) == [1.0, None, None]


def test_page_is_usable():
    assert tlq.page_is_usable(CLEAN)
    assert not tlq.page_is_usable(GARBAGE)
    assert not tlq.page_is_usable([])
    assert tlq.page_is_usable(["два", "слова"])  # оценивать не по чему — берём
    # 0.95 — ниже порога PAGE_MIN_QUALITY: на таких страницах ~12% строк с ошибками
    almost = CLEAN * 4 + ["BATCH"]
    assert 0.9 < tlq.text_quality(almost) < tlq.PAGE_MIN_QUALITY
    assert not tlq.page_is_usable(almost)


def test_diagnose_layer_good_layer():
    result = tlq.diagnose_layer([CLEAN] * 5)
    assert result["recommend"] == "text_layer"
    assert result["median_quality"] == 1.0 and result["usable_pages"] == 5


def test_diagnose_layer_garbage_layer_goes_to_ocr():
    result = tlq.diagnose_layer([GARBAGE] * 5)
    assert result["recommend"] == "ocr"
    assert result["usable_pages"] == 0


def test_diagnose_layer_mixed():
    result = tlq.diagnose_layer([CLEAN, GARBAGE, [], CLEAN])
    assert result["recommend"] == "mixed"
    assert result["usable_pages"] == 2 and result["pages_without_text"] == 1


def test_diagnose_layer_without_text_goes_to_ocr():
    result = tlq.diagnose_layer([[], []])
    assert result["recommend"] == "ocr"
    assert result["pages_without_text"] == 2 and result["median_quality"] is None


def test_latin_in_cyrillic_text_is_garbage_except_acronyms():
    # обрывки из пятен/печатей на титуле РТМ 7-120-82
    for word in ["oma", "rfP", "ftHi", "H", "9mmi"]:
        assert not tlq.word_ok(word, cyrillic_text=True), word
    assert tlq.word_ok("ISO", cyrillic_text=True)
    assert tlq.word_ok("GOST", cyrillic_text=True)


def test_spaced_letters_are_garbage():
    spaced = "Н е г а т и в н ы е м а с к и".split()
    assert tlq.text_quality(spaced) == 0.0
    # обычные однобуквенные предлоги поодиночке — не разрядка
    assert tlq.text_quality("в соответствии с ГОСТ и в срок".split()) == 1.0


def test_spaced_letter_mask_marks_only_long_runs():
    words = ["слово", "а", "б", "слово", "в", "г", "д", "е"]
    assert tlq.spaced_letter_mask(words) == [False] * 4 + [True] * 4


def test_soft_hyphen_markers_are_ignored():
    assert tlq.word_ok("фо\ufffe")
    assert tlq.word_ok("стан\u00adдарт")
