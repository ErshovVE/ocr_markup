# Tests and linting

<p align="center">
  <strong>Language:</strong>
  <b>English</b> |
  <a href="ru/testing.md">🇷🇺 Русский</a>
</p>

## Installing dev dependencies

```bash
pip install -r requirements-dev.txt
```

## Tests

```bash
pytest
pytest --cov=src --cov=backend --cov-report=term-missing
```

Tests cover `src/` (models, backups, annotations), `backend/consensus.py`,
`backend/pdf_extract.py`, `backend/models_status.py`, and `backend/pipeline.py`
(pure logic only, no ML calls — the engine-call timeout, crop naming/resume
scheme) and `backend/jobs.py` (`pipeline.run` is mocked out — no real ML calls
are made). `backend/detector.py` and `backend/recognizers.py` aren't tested —
they lazily import heavy ML dependencies (PaddleOCR, SuryaOCR, pytesseract)
only inside their methods and need real models/a system Tesseract, which
doesn't fit unit tests (see `backend/README.md`). `backend/pdf_extract.py`
uses `pypdfium2` — a light, self-contained library with no downloadable
models or system binaries — so unlike the above, it's fully unit-tested
against synthetic PDFs (`pypdfium2` and `numpy` were added to
`requirements-dev.txt` specifically for this).

## Linting

[ruff](https://docs.astral.sh/ruff/) is used both as the linter and the
formatter (`pyproject.toml`, `[tool.ruff]` section):

```bash
ruff check .
ruff format .
```

The pyupgrade rules (`UP`) are deliberately disabled — the project
intentionally keeps `Dict`/`List`/`Optional` from `typing` instead of
`dict`/`list`/`X | None` (see `CLAUDE.md`, "Code Style" section), and `UP`
would suggest rewriting that.
