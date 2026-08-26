# Docker

<p align="center">
  <strong>Language:</strong>
  <b>English</b> |
  <a href="ru/docker.md">🇷🇺 Русский</a>
</p>

Two independent services — they don't talk to each other over the network,
each has its own Dockerfile:

| Service | Dockerfile | What's inside | Port |
|---|---|---|---|
| `frontend` | `frontend/Dockerfile` | The Streamlit app `frontend/app.py` + `frontend/src/` | 8501 |
| `backend` | `backend/Dockerfile` | The FastAPI consensus spike (`backend/`) — PaddleOCR + SuryaOCR + Tesseract | 8756 |

## Running via docker compose

```bash
docker compose up --build
```

- Frontend: http://localhost:8501
- Backend: http://localhost:8756 (see `backend/README.md` for the API reference)

Both services mount `./data` (create this folder on the host and put your
working directory with images/annotations there) at `/data` inside the
container — this is the only way to pass real files into the container,
since the apps have no access to the rest of the host filesystem.

`backend` additionally uses the named volumes `paddleocr-models`/`surya-models`
so PaddleOCR/SuryaOCR models are downloaded once and survive container
recreation.

## Building and running individually

Frontend (build context — repo root):

```bash
docker build -f frontend/Dockerfile -t ocr-markup-frontend .
docker run --rm -p 8501:8501 -v "$(pwd)/data:/data" ocr-markup-frontend
```

Backend (build context — repo root, not `backend/`, since the image uses the
absolute import `backend.main`):

```bash
docker build -f backend/Dockerfile -t ocr-markup-backend .
docker run --rm -p 8756:8756 -v "$(pwd)/data:/data" ocr-markup-backend
```

## Important

- The backend is an unauthenticated spike that accepts an arbitrary
  `input_dir`/`output_dir` in the request body (see `backend/README.md`).
  Inside the container those paths are constrained by the mounted volumes,
  but don't unnecessarily point the `docker run`/`docker compose` `volumes`
  section at production data.
- The backend image is heavy (PaddleOCR + SuryaOCR + system Tesseract) — the
  first build and first run (downloading ML models) can take a while.
- The frontend image doesn't include `predict.py`/`predict.ipynb` or the
  PyInstaller wiring (`frontend/wrapper.py`, `frontend/pyinst_command.txt`,
  `frontend/build_exe.py`, `frontend/requirements-build.txt`) — they aren't
  part of running the app (see `CLAUDE.md`).
