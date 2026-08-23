from collections import Counter
from typing import Dict, Optional, Tuple


def vote(
    results: Dict[str, Tuple[str, float]],
    threshold: float,
    preferred_model: Optional[str] = None,
    min_agree: int = 2,
) -> Tuple[str, str, str, bool]:
    """Голосование по результатам движков распознавания: (bucket, text, engine, diverged)

    min_agree — сколько движков должны сойтись в одном тексте, чтобы принять
    его без разбора уверенности отдельных движков ("N из M" схема выбора
    движков, см. frontend/src/ui/generation_view.py). При min_agree <= 1
    сверка большинства пропускается вовсе — побеждает единственный уверенный
    движок (или предпочитаемый/лучший по score, см. фолбэк ниже), сверять
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

    if preferred_model and preferred_model in results:
        text, score = results[preferred_model]
        if score >= threshold:
            return "good", text, preferred_model, diverged

    best_engine = max(results, key=lambda eng: results[eng][1])
    best_text, best_score = results[best_engine]
    if best_score >= threshold:
        return "good", best_text, best_engine, diverged

    return "needs_review", best_text, best_engine, diverged
