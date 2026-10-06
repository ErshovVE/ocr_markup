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

`backend/degrade.py` (page degradation, `backend/tests/test_degrade.py`): the line
legibility check, effect-spec validation, page seeds, the text-layer path of
`pipeline.run` (with the degradation call mocked) and the `degrade_*` request
validation run without Augraphy. The few tests that need real Augraphy (page
geometry, the default effect set, the preview CLI, API validation of the default
set) are `pytest.importorskip("augraphy")` — `augraphy` (numba, scikit-image, …)
is deliberately not in `requirements-dev.txt`; it comes with
`backend/requirements.txt`, so run those in the backend environment/image.

## Linting

[ruff](https://docs.astral.sh/ruff/) is used both as the linter and the
formatter (`pyproject.toml`, `[tool.ruff]` section):

```bash
ruff check .
ruff format .
```

The pyupgrade rules (`UP`) are deliberately disabled — the project
intentionally keeps `Dict`/`List`/`Optional` from `typing` instead of
`dict`/`list`/`X | None`, and `UP` would suggest rewriting that.
