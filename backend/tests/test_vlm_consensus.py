"""Юнит-тесты IoU-геометрии и консенсуса VLM (backend/vlm_geometry, vlm_consensus)."""

from backend import vlm_consensus
from backend.vlm_geometry import clamped_bbox, iou, rect_polygon


def _rect(x0, y0, x1, y1):
    return rect_polygon(x0, y0, x1, y1)


def test_iou_full_overlap_is_one():
    poly = _rect(0, 0, 10, 10)

    assert iou(poly, poly) == 1.0


def test_iou_disjoint_is_zero():
    assert iou(_rect(0, 0, 10, 10), _rect(100, 100, 110, 110)) == 0.0


def test_iou_half_horizontal_shift():
    # A и B по 100 px², пересечение 5*10=50, объединение 150 → 1/3
    value = iou(_rect(0, 0, 10, 10), _rect(5, 0, 15, 10))

    assert abs(value - 1 / 3) < 1e-9


def test_clamped_bbox_uses_all_vertices_of_a_skewed_quad():
    # Наклонный четырёхугольник: box[0]/box[2] — не левый-верх/правый-низ.
    quad = [[10, 5], [100, 0], [95, 30], [5, 35]]

    assert clamped_bbox(quad, 1000, 1000) == (5, 0, 100, 35)


def test_clamped_bbox_clamps_to_image_and_rounds_outward():
    poly = [[-3.5, -1.2], [120.2, -1.2], [120.2, 50.1], [-3.5, 50.1]]

    assert clamped_bbox(poly, 100, 40) == (0, 0, 100, 40)
    assert clamped_bbox([[1.7, 2.2], [9.1, 2.2], [9.1, 7.6], [1.7, 7.6]], 100, 100) == (1, 2, 10, 8)


def test_group_by_iou_single_engine_one_group_per_box():
    per_engine = {"a": [(_rect(0, 0, 10, 10), "x"), (_rect(0, 20, 10, 30), "y")]}

    groups = vlm_consensus.group_by_iou(per_engine, 0.5)

    assert len(groups) == 2
    assert [g["texts"] for g in groups] == [{"a": "x"}, {"a": "y"}]


def test_group_by_iou_matches_boxes_across_engines():
    box = _rect(0, 0, 10, 10)
    per_engine = {"a": [(box, "текст")], "b": [(box, "текст")], "c": [(box, "текст")]}

    groups = vlm_consensus.group_by_iou(per_engine, 0.5)

    assert len(groups) == 1
    assert groups[0]["texts"] == {"a": "текст", "b": "текст", "c": "текст"}


def test_group_by_iou_leaves_unmatched_box_as_own_group():
    per_engine = {
        "a": [(_rect(0, 0, 10, 10), "shared")],
        "b": [(_rect(0, 0, 10, 10), "shared"), (_rect(0, 50, 10, 60), "extra")],
    }

    groups = vlm_consensus.group_by_iou(per_engine, 0.5)

    assert {"a": "shared", "b": "shared"} in [g["texts"] for g in groups]
    assert {"b": "extra"} in [g["texts"] for g in groups]


def test_resolve_two_agree_is_good():
    group = {"poly": _rect(0, 0, 10, 10), "texts": {"a": "слово", "b": "слово"}}

    bucket, text, engine, diverged = vlm_consensus.resolve(group, vlm_min_agree=2)

    assert (bucket, text, diverged) == ("good", "слово", False)
    assert engine in ("a", "b")


def test_resolve_all_disagree_is_needs_review_and_diverged():
    group = {"poly": _rect(0, 0, 10, 10), "texts": {"a": "икс", "b": "игрек"}}

    bucket, _, _, diverged = vlm_consensus.resolve(group, vlm_min_agree=2)

    assert bucket == "needs_review"
    assert diverged is True


def test_resolve_single_engine_non_empty_is_good():
    group = {"poly": _rect(0, 0, 10, 10), "texts": {"a": "один"}}

    assert vlm_consensus.resolve(group, vlm_min_agree=1)[:2] == ("good", "один")


def test_resolve_empty_text_is_not_good():
    group = {"poly": _rect(0, 0, 10, 10), "texts": {"a": "   "}}

    assert vlm_consensus.resolve(group, vlm_min_agree=1) == ("needs_review", "", "", False)
