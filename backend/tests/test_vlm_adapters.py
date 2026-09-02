"""Юнит-тесты парсеров ответов VLM (backend/vlm_adapters.py).

Фикстуры — сырые строки ответов моделей; сети/реальных моделей нет.
"""

from backend import vlm_adapters


def test_parse_hunyuan_spotting_extracts_rectangular_polygon():
    lines = vlm_adapters.parse_hunyuan_spotting("Привет мир(10,20),(100,45)")

    assert lines == [([[10, 20], [100, 20], [100, 45], [10, 45]], "Привет мир")]


def test_parse_hunyuan_spotting_handles_multiple_lines():
    raw = "первая(0,0),(50,10)\nвторая(0,12),(60,22)"

    lines = vlm_adapters.parse_hunyuan_spotting(raw)

    assert [text for _, text in lines] == ["первая", "вторая"]


def test_parse_dotsocr_strips_json_fence():
    raw = '```json\n[{"bbox": [1, 2, 30, 40], "category": "Text", "text": "a"}]\n```'

    lines = vlm_adapters.parse_dotsocr(raw)

    assert lines == [([[1, 2], [30, 2], [30, 40], [1, 40]], "a")]


def test_parse_dotsocr_skips_picture_category():
    raw = '[{"bbox": [0, 0, 5, 5], "category": "Picture", "text": "logo"}]'

    assert vlm_adapters.parse_dotsocr(raw) == []


def test_parse_dotsocr_returns_empty_on_broken_json():
    assert vlm_adapters.parse_dotsocr("это не json") == []


def test_parse_unlimited_ocr_reads_ref_box_tokens():
    raw = "<ref>заголовок</ref><box>(12,34),(210,60)</box> прочее"

    lines = vlm_adapters.parse_unlimited_ocr(raw)

    assert lines == [([[12, 34], [210, 34], [210, 60], [12, 60]], "заголовок")]


def test_parse_unlimited_ocr_denormalizes_permille_coords():
    # координаты 0..1000 приводятся к пикселям по размеру страницы
    raw = "<ref>x</ref><box>(0,0),(500,500)</box>"

    lines = vlm_adapters.parse_unlimited_ocr(raw, image_w=2000, image_h=4000)

    assert lines[0][0] == [[0, 0], [1000, 0], [1000, 2000], [0, 2000]]


def test_parse_paddleocr_vl_reads_parallel_arrays():
    raw = '{"rec_texts": ["строка"], "rec_polys": [[[1, 1], [9, 1], [9, 5], [1, 5]]]}'

    lines = vlm_adapters.parse_paddleocr_vl(raw)

    assert lines == [([[1, 1], [9, 1], [9, 5], [1, 5]], "строка")]


def test_parse_glm_ocr_returns_text_lines_without_boxes():
    raw = "```markdown\nпервая строка\nвторая строка\n```"

    assert vlm_adapters.parse_glm_ocr(raw) == ["первая строка", "вторая строка"]


def test_postprocess_text_removes_markdown_fence():
    assert vlm_adapters.postprocess_text("```\nx\n```") == "x"


def test_postprocess_text_replaces_latex_macros_and_collapses_spaces():
    assert vlm_adapters.postprocess_text(r"a  \times   b") == "a × b"


def test_parse_hunyuan_spotting_skips_coordinate_only_lines():
    # строка без текста перед координатами не попадает в результат
    assert vlm_adapters.parse_hunyuan_spotting("(1,2),(3,4)") == []


def test_parse_paddleocr_vl_reads_element_list_with_bbox():
    raw = '[{"bbox": [5, 6, 50, 20], "rec_text": "элемент"}]'

    assert vlm_adapters.parse_paddleocr_vl(raw) == [
        ([[5, 6], [50, 6], [50, 20], [5, 20]], "элемент")
    ]


def test_parse_paddleocr_vl_reads_polygon_bbox():
    raw = '{"elements": [{"poly": [[1, 1], [9, 1], [9, 4], [1, 4]], "text": "p"}]}'

    assert vlm_adapters.parse_paddleocr_vl(raw) == [([[1, 1], [9, 1], [9, 4], [1, 4]], "p")]


def test_parse_paddleocr_vl_returns_empty_on_broken_json():
    assert vlm_adapters.parse_paddleocr_vl("{oops") == []


def test_parse_glm_ocr_via_dispatcher_returns_list_of_strings():
    assert vlm_adapters.parse("glm_ocr", "одна\nдве") == ["одна", "две"]


def test_postprocess_text_empty_input_returns_empty():
    assert vlm_adapters.postprocess_text("") == ""
    assert vlm_adapters.postprocess_text(None) == ""


def test_parse_dispatcher_routes_by_engine_id():
    assert vlm_adapters.parse("dots_ocr", '[{"bbox":[0,0,20,20],"text":"z"}]') == [
        ([[0, 0], [20, 0], [20, 20], [0, 20]], "z")
    ]
    assert vlm_adapters.parse("unknown_engine", "whatever") == []
