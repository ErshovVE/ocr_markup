"""Юнит-тесты парсеров ответов VLM (backend/vlm_adapters.py).

Фикстуры — сырые строки ответов моделей; сети/реальных моделей нет.
"""

from backend import vlm_adapters


def test_parse_hunyuan_spotting_denormalizes_0_1000_coords_to_pixels():
    """Координаты HunyuanOCR — [0, 1000] (официальный denormalize_coordinates)."""
    lines = vlm_adapters.parse_hunyuan_spotting("Привет мир(100,200),(500,450)", 2000, 1000)

    assert lines == [([[200, 200], [1000, 200], [1000, 450], [200, 450]], "Привет мир")]


def test_parse_hunyuan_spotting_handles_multiple_lines():
    raw = "первая(0,0),(50,10)\nвторая(0,12),(60,22)"

    lines = vlm_adapters.parse_hunyuan_spotting(raw)

    assert [text for _, text in lines] == ["первая", "вторая"]


def test_parse_region_text_returns_text_lines_without_boxes():
    raw = "```markdown\nпервая строка\nвторая строка\n```"

    assert vlm_adapters.parse_region_text(raw) == ["первая строка", "вторая строка"]


def test_postprocess_text_removes_markdown_fence():
    assert vlm_adapters.postprocess_text("```\nx\n```") == "x"


def test_postprocess_text_replaces_latex_macros_and_collapses_spaces():
    assert vlm_adapters.postprocess_text(r"a  \times   b") == "a × b"


def test_parse_hunyuan_spotting_skips_coordinate_only_lines():
    # строка без текста перед координатами не попадает в результат
    assert vlm_adapters.parse_hunyuan_spotting("(1,2),(3,4)") == []


def test_parse_glm_ocr_via_dispatcher_returns_list_of_strings():
    assert vlm_adapters.parse("glm_ocr", "одна\nдве") == ["одна", "две"]


def test_postprocess_text_empty_input_returns_empty():
    assert vlm_adapters.postprocess_text("") == ""
    assert vlm_adapters.postprocess_text(None) == ""


_PVL = (
    "<|TEXT_START|>Первая строка<|TEXT_END|><|LOC_BEGIN|>"
    "<|LOC_100|><|LOC_200|><|LOC_500|><|LOC_190|><|LOC_505|><|LOC_450|><|LOC_95|><|LOC_460|>"
    "<|LOC_END|>"
    "<|TEXT_START|>Вторая<|TEXT_END|><|LOC_BEGIN|>"
    "<|LOC_0|><|LOC_500|><|LOC_250|><|LOC_500|><|LOC_250|><|LOC_600|><|LOC_0|><|LOC_600|>"
    "<|LOC_END|>"
)


def test_parse_paddleocr_vl_spotting_denormalizes_quads_to_axis_boxes():
    """PaddleOCR-VL 1.6 "Spotting:": 4 точки в [0, 1000] → осевой bbox в пикселях
    (порт PaddleX post_process_for_spotting)."""
    lines = vlm_adapters.parse_paddleocr_vl_spotting(_PVL, 2000, 1000)

    assert lines == [
        ([[190, 190], [1010, 190], [1010, 460], [190, 460]], "Первая строка"),
        ([[0, 500], [500, 500], [500, 600], [0, 600]], "Вторая"),
    ]


def test_parse_paddleocr_vl_spotting_without_special_loc_markers():
    """LOC_BEGIN/LOC_END — special-токены, сервер может их вырезать: фолбэк
    режет поток <|LOC_n|> на группы по 8, как PaddleX."""
    stripped = _PVL.replace("<|LOC_BEGIN|>", "").replace("<|LOC_END|>", "")

    lines = vlm_adapters.parse_paddleocr_vl_spotting(stripped, 2000, 1000)

    assert [text for _, text in lines] == ["Первая строка", "Вторая"]
    assert lines[1][0] == [[0, 500], [500, 500], [500, 600], [0, 600]]


def test_parse_paddleocr_vl_spotting_ignores_incomplete_and_empty():
    assert vlm_adapters.parse_paddleocr_vl_spotting("<|LOC_1|><|LOC_2|>", 100, 100) == []
    assert vlm_adapters.parse_paddleocr_vl_spotting("", 100, 100) == []


def test_parse_dispatcher_routes_native_and_layout_engines():
    assert vlm_adapters.parse("hunyuan_ocr", "z(0,0),(100,100)", 20, 20) == [
        ([[0, 0], [2, 0], [2, 2], [0, 2]], "z")
    ]
    for engine in ("glm_ocr", "dots_ocr", "unlimited_ocr"):
        assert vlm_adapters.parse(engine, "строка") == ["строка"]
    assert vlm_adapters.parse("unknown_engine", "whatever") == []


def test_parse_dispatcher_swallows_unexpected_parser_error(monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("parser blew up")

    monkeypatch.setitem(vlm_adapters._NATIVE_PARSERS, "hunyuan_ocr", boom)

    assert vlm_adapters.parse("hunyuan_ocr", "x") == []


def test_official_prompts():
    assert vlm_adapters.PROMPTS == {
        "paddleocr_vl": "Spotting:",
        "hunyuan_ocr": "检测并识别图片中的文字，将文本坐标格式化输出。",
        "glm_ocr": "Text Recognition:",
        "dots_ocr": "Extract the text content from this image.",
        "unlimited_ocr": "Free OCR.",
    }


def test_line_prompts_cover_line_vlm_engines():
    from backend.config import LINE_VLM_ENGINES

    assert set(vlm_adapters.LINE_PROMPTS) == set(LINE_VLM_ENGINES)
    assert vlm_adapters.LINE_PROMPTS["paddleocr_vl"] == "OCR:"


def test_parse_line_text_joins_wrapped_lines_and_handles_empty():
    assert vlm_adapters.parse_line_text("первая часть\nвторая часть\n") == (
        "первая часть вторая часть"
    )
    assert vlm_adapters.parse_line_text("") == ""
    assert vlm_adapters.parse_line_text(None) == ""
