from collections import Counter
from typing import Dict, Optional, Tuple


def vote(
    results: Dict[str, Tuple[str, float]],
    threshold: float,
    preferred_model: Optional[str] = None,
) -> Tuple[str, str, str]:
    """Голосование по результатам движков распознавания: (bucket, text, engine)"""
    if not results:
        return "needs_review", "", ""

    texts = [text for text, _ in results.values() if text]
    if texts:
        counts = Counter(texts)
        winner_text, winner_count = counts.most_common(1)[0]
        if winner_count >= 2:
            winner_engine = next(
                eng for eng, (text, _) in results.items() if text == winner_text
            )
            return "good", winner_text, winner_engine

    if preferred_model and preferred_model in results:
        text, score = results[preferred_model]
        if score >= threshold:
            return "good", text, preferred_model

    best_engine = max(results, key=lambda eng: results[eng][1])
    best_text, best_score = results[best_engine]
    if best_score >= threshold:
        return "good", best_text, best_engine

    return "needs_review", best_text, best_engine
