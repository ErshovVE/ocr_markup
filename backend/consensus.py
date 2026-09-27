from collections import Counter
from typing import Dict, Optional, Tuple


def vote(
    results: Dict[str, Tuple[str, float]],
    threshold: float,
    preferred_model: Optional[str] = None,
    min_agree: int = 2,
) -> Tuple[str, str, str, bool]:
    """Голосование по результатам движков распознавания: (bucket, text, engine, diverged)

    min_agree — сколько движков должны выдать посимвольно одинаковый текст
    ("N из M" схема, см. frontend/src/ui/generation_view.py). При min_agree >= 2
    это единственный путь в "good": без такого совпадения строка уходит в
    needs_review, какой бы уверенной ни была отдельная модель (раньше
    срабатывал фолбэк "предпочитаемый/лучший по score >= threshold", и "2 из 3"
    на деле означало "хватит одного уверенного движка"). Текст при этом —
    подсказка разметчику: предпочитаемый движок, иначе лучший по score.
    Порог уверенности (threshold) решает только при min_agree <= 1 — сверять
    там не с кем.

    diverged=True — минимум 2 движка независимо друг от друга уверены
    (score >= threshold), но их тексты не совпадают. Это отдельный сигнал для
    статистики/трекера прогресса (backend/jobs.py): в отличие от обычного
    needs_review (никто не уверен), здесь несколько движков уверены, но
    расходятся между собой.
    """
    confident_texts = {text for text, score in results.values() if text and score >= threshold}
    diverged = len(confident_texts) >= 2

    if not results:
        return "needs_review", "", "", diverged

    if min_agree >= 2:
        texts = [text for text, _ in results.values() if text]
        if texts:
            counts = Counter(texts)
            winner_text, winner_count = counts.most_common(1)[0]
            if winner_count >= min_agree:
                winner_engine = next(
                    eng for eng, (text, _) in results.items() if text == winner_text
                )
                return "good", winner_text, winner_engine, diverged
        hint_engine = _hint_engine(results, preferred_model)
        return "needs_review", results[hint_engine][0], hint_engine, diverged

    if preferred_model and preferred_model in results:
        text, score = results[preferred_model]
        if score >= threshold:
            return "good", text, preferred_model, diverged

    best_engine = max(results, key=lambda eng: results[eng][1])
    best_text, best_score = results[best_engine]
    if best_score >= threshold:
        return "good", best_text, best_engine, diverged

    return "needs_review", best_text, best_engine, diverged


def _hint_engine(results: Dict[str, Tuple[str, float]], preferred_model: Optional[str]) -> str:
    """Движок, чей текст показать разметчику в needs_review: предпочитаемый,
    если он что-то распознал, иначе лучший по score."""
    if preferred_model and results.get(preferred_model, ("", 0.0))[0]:
        return preferred_model
    return max(results, key=lambda eng: results[eng][1])
