# Тесты и линтер

## Установка dev-зависимостей

```bash
pip install -r requirements-dev.txt
```

## Тесты

```bash
pytest
pytest --cov=src --cov=backend --cov-report=term-missing
```

Тесты покрывают `src/` (модели, бэкапы, аннотации), `backend/consensus.py`,
`backend/pdf_extract.py`, `backend/models_status.py`, а также
`backend/pipeline.py` (только чистая логика без ML-вызовов — таймаут на
вызовы движков, схема именования/резюмирования кропов) и `backend/jobs.py`
(`pipeline.run` подменяется моком — реальные ML-вызовы не выполняются).
`backend/detector.py` и `backend/recognizers.py` не тестируются — они лениво
импортируют тяжёлые ML-зависимости (PaddleOCR, SuryaOCR, pytesseract) только
внутри методов и требуют реальных моделей/системного Tesseract, что не подходит
для юнит-тестов (см. `backend/README.md`). `backend/pdf_extract.py`
использует `pypdfium2` — лёгкую самодостаточную библиотеку без скачиваемых
моделей и системных бинарников — поэтому, в отличие от них, полностью
юнит-тестируется на синтетических PDF (`pypdfium2` и `numpy` добавлены в
`requirements-dev.txt` именно для этого).

## Линтер

[ruff](https://docs.astral.sh/ruff/) используется и как линтер, и как
форматтер (`pyproject.toml`, секция `[tool.ruff]`):

```bash
ruff check .
ruff format .
```

Правила pyupgrade (`UP`) намеренно не включены — проект сознательно сохраняет
`Dict`/`List`/`Optional` из `typing` вместо `dict`/`list`/`X | None`
(см. `CLAUDE.md`, раздел «Code Style»), и `UP` предлагал бы это переписать.
