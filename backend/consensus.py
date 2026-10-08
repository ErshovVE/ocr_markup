from collections import Counter
from typing import Callable, Dict, Optional, Tuple


def vote(
    results: Dict[str, Tuple[str, float]],
    threshold: float,
    preferred_model: Optional[str] = None,
    min_agree: int = 2,
    key: Optional[Callable[[str], str]] = None,
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

    key — функция-ключ сравнения текстов (backend/text_keys.py): совпадение и
    diverged считаются по key(text), а не по тексту. Возвращается текст
    движка, а не ключ: предпочитаемого, если его ключ победил, иначе первого
    по порядку results из согласной группы. None — посимвольно, как раньше.
    """
    key_of = key or _identity
    diverged = is_diverged(results, threshold, key)

    if not results:
        return "needs_review", "", "", diverged

    if min_agree >= 2:
        keys = [key_of(text) for text, _ in results.values() if text]
        if keys:
            winner_key, winner_count = Counter(keys).most_common(1)[0]
            if winner_count >= min_agree:
                winner_engine = _winner_engine(results, winner_key, key_of, preferred_model)
                return "good", results[winner_engine][0], winner_engine, diverged
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


def is_diverged(
    results: Dict[str, Tuple[str, float]],
    threshold: float,
    key: Optional[Callable[[str], str]] = None,
) -> bool:
    """Минимум 2 уверенных (score >= threshold) голоса с разными ключами текста.
    Отдельно от vote() — режим crops считает его без голоса исходной метки
    (backend/pipeline_crops.py), иначе почти каждая строка была бы diverged."""
    key_of = key or _identity
    confident = {key_of(text) for text, score in results.values() if text and score >= threshold}
    return len(confident) >= 2


def _identity(text: str) -> str:
    return text


def _winner_engine(
    results: Dict[str, Tuple[str, float]],
    winner_key: str,
    key_of: Callable[[str], str],
    preferred_model: Optional[str],
) -> str:
    """Чей текст писать для победившего ключа: предпочитаемого движка, если он
    в согласной группе, иначе первого по порядку results."""
    if preferred_model in results:
        text = results[preferred_model][0]
        if text and key_of(text) == winner_key:
            return preferred_model
    return next(eng for eng, (text, _) in results.items() if text and key_of(text) == winner_key)


def _hint_engine(results: Dict[str, Tuple[str, float]], preferred_model: Optional[str]) -> str:
    """Движок, чей текст показать разметчику в needs_review: предпочитаемый,
    если он что-то распознал, иначе лучший по score."""
    if preferred_model and results.get(preferred_model, ("", 0.0))[0]:
        return preferred_model
    return max(results, key=lambda eng: results[eng][1])
