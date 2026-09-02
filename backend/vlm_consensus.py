"""IoU-консенсус нескольких VLM: боксы+тексты → строки good/needs_review.

Ни одна VLM не даёт per-line confidence, поэтому порог уверенности из
классического пути (score_threshold) здесь неприменим. Вместо него:
  1. боксы от разных движков сопоставляются по IoU (group_by_iou);
  2. внутри группы побеждает текст, который отдали >= vlm_min_agree движков.

resolve() повторяет мажоритарную логику backend.consensus.vote() (Counter +
most_common), но без фолбэка "лучший по score" — при псевдо-score = 1.0 у
всех движков этот фолбэк всегда бы срабатывал и любой непустой текст (и даже
расхождение) уходил бы в "good". diverged=True — >= 2 разных непустых текста.

Чистая геометрия/логика — полностью юнит-тестируется (test_vlm_consensus.py).
"""

from collections import Counter
from typing import Dict, List, Tuple

from backend.vlm_adapters import postprocess_text
from backend.vlm_geometry import iou, merge_adjacent, polygon_bbox, rect_polygon

__all__ = [
    "iou",
    "merge_adjacent",
    "polygon_bbox",
    "rect_polygon",
    "group_by_iou",
    "resolve",
]

# per_engine: {engine_id: [(polygon, text), ...]}
PerEngineLines = Dict[str, List[Tuple[list, str]]]


def group_by_iou(per_engine: PerEngineLines, iou_threshold: float) -> List[Dict]:
    """Жадная кластеризация боксов разных движков в строки.

    Порядок движков в per_engine — приоритет опорного бокса. Для каждого бокса
    опорного движка ищем лучший по IoU (>= iou_threshold) бокс у каждого из
    остальных движков и забираем его в группу. Несопоставленные боксы любого
    движка становятся группой из одного участника.

    Возвращает список ``{"poly": <опорный полигон>, "texts": {engine: text}}``.
    """
    engine_order = list(per_engine.keys())
    remaining: PerEngineLines = {e: list(per_engine.get(e, [])) for e in engine_order}
    groups: List[Dict] = []

    for anchor in engine_order:
        for anchor_poly, anchor_text in remaining[anchor]:
            texts = {anchor: anchor_text}
            for other in engine_order:
                if other == anchor:
                    continue
                best_idx = None
                best_iou = iou_threshold
                for idx, (other_poly, _) in enumerate(remaining[other]):
                    value = iou(anchor_poly, other_poly)
                    if value >= best_iou:
                        best_iou = value
                        best_idx = idx
                if best_idx is not None:
                    _, matched_text = remaining[other].pop(best_idx)
                    texts[other] = matched_text
            groups.append({"poly": anchor_poly, "texts": texts})
        remaining[anchor] = []

    return groups


def resolve(group: Dict, vlm_min_agree: int) -> Tuple[str, str, str, bool]:
    """Группа сопоставленных боксов → (bucket, text, engine, diverged).

    Пустые (после postprocess_text) ответы движков не считаются — если не
    осталось ни одного непустого текста, строка уходит в needs_review без
    ложного "good". Побеждает самый частый непустой текст; "good" — если его
    отдали не меньше vlm_min_agree движков, иначе needs_review.
    """
    texts = {engine: postprocess_text(text) for engine, text in group["texts"].items()}
    non_empty = {engine: text for engine, text in texts.items() if text}
    diverged = len(set(non_empty.values())) >= 2

    if not non_empty:
        return "needs_review", "", "", False

    winner_text, winner_count = Counter(non_empty.values()).most_common(1)[0]
    winner_engine = next(engine for engine, text in non_empty.items() if text == winner_text)
    bucket = "good" if winner_count >= vlm_min_agree else "needs_review"
    return bucket, winner_text, winner_engine, diverged
