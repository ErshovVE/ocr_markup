# Docker

<p align="center">
  <strong>Language:</strong>
  <b>English</b> |
  <a href="ru/docker.md">🇷🇺 Русский</a>
</p>

Two services, each with its own Dockerfile. The frontend reaches the backend
over the compose network (`CONSENSUS_BACKEND_URL=http://backend:8756`); the
optional VLM model servers are described [below](#vlm-mode--optional-companion-services):

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

All published ports are bound to `127.0.0.1` (see the note at the top of
`docker-compose.yml`): the backend has no authentication and the frontend runs
with XSRF protection disabled, so neither may be reachable from the LAN. Other
hosts on your network cannot reach them; only this machine can.

Both services mount `./data` (create this folder on the host and put your
working directory with images/annotations there) at `/data` inside the
container — this is the only way to pass real files into the container,
since the apps have no access to the rest of the host filesystem. The backend
also sets `OCR_DATA_ROOT=/data`, so `POST /run` rejects `input_dir`/`output_dir`
that resolve outside `/data`.

`backend` additionally uses the named volumes `paddleocr-models`/`surya-models`
so PaddleOCR/SuryaOCR models are downloaded once and survive container
recreation.

## VLM mode — optional companion services

The `mode="vlm"` auto-labeling path (see `backend/README.md`) needs a model
server. It's **one engine for all five models — llama.cpp `llama-server`** in
router mode, declared in `docker-compose.yml` under **profiles**, so
`docker compose up` does **not** start it by default. Pick **one** profile (they
share the port and the `llama-vlm` name):

```bash
docker compose --profile vlm-cpu up -d      # CPU (llama.cpp:server)
docker compose --profile vlm-gpu up -d      # GPU (llama.cpp:server-cuda; needs nvidia-container-toolkit)
```

or the wrapper scripts (they also self-check `GET /models/status`):

```bash
./scripts/vlm/setup.sh --cpu            # Linux / macOS / WSL
./scripts/vlm/setup.sh --gpu
./scripts/vlm/setup.sh --native         # no Docker: GGUF into .vlm/ + local llama-server
```
```powershell
.\scripts\vlm\setup.ps1 -Cpu            # Windows
.\scripts\vlm\setup.ps1 -Gpu
.\scripts\vlm\setup.ps1 -Native
```

| Service | Profile | Port | What it does |
|---|---|---|---|
| `vlm-models` | `vlm-cpu`, `vlm-gpu` | — | one-shot init: downloads the GGUF files into the `vlm-models` volume (pinned HF commits, `scripts/vlm/fetch_models.py`) and patches PaddleOCR-VL's mmproj for `Spotting:` |
| `llama-vlm` | `vlm-cpu` | 8080 | `llama-server --models-preset scripts/vlm/models.ini --models-max 1` |
| `llama-vlm-gpu` | `vlm-gpu` | 8080 | the same on the CUDA build, network alias `llama-vlm` |

- The `backend` service already gets `VLM_ENDPOINT=http://llama-vlm:8080`;
  don't put a `localhost` value into `.env` (see `.env.example`).
- **At most one model in memory** (`--models-max 1`, `VLM_MODELS_MAX`): the model
  is loaded on the first request for it and evicts the previous one. The backend
  processes the folder model by model, so a VLM job switches models only
  `len(vlm_engines)` times.
- `VLM_MODELS=glm-ocr,dots-ocr` downloads only some models (preset names from
  `scripts/vlm/models.ini`); the rest show as `error` in `/models/status`.
- The first start downloads several GB (Q8_0 weights). `llama-vlm` starts only
  after `vlm-models` has finished (`docker compose logs -f vlm-models`). Check
  readiness in `GET /models/status` (`vlm_*` keys) or the frontend "📦 Models" tab.
- GPU: `VLM_GPU` picks the card (default 0).

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

- Published ports bind to `127.0.0.1` only (see above). If you change that in
  `docker-compose.yml`, you expose an unauthenticated backend and an
  XSRF-disabled Streamlit to the whole network — don't, unless you know
  exactly what you're doing.
- The backend is an unauthenticated spike that accepts an arbitrary
  `input_dir`/`output_dir` in the request body (see `backend/README.md`).
  `OCR_DATA_ROOT=/data` (set in `docker-compose.yml`) confines them to the
  mounted volume; don't unnecessarily point the `volumes` section at
  production data.
- The backend image is heavy (PaddleOCR + SuryaOCR + system Tesseract) — the
  first build and first run (downloading ML models) can take a while.
- The VLM model server is pinned: llama.cpp image by build number
  (`server-b11206`), GGUF files by Hugging Face commit. llama.cpp doesn't execute
  code from model repositories. Unlimited-OCR's GGUF is a community build — the
  only one available.
- The frontend image doesn't include `predict.py`/`predict.ipynb` or the
  PyInstaller wiring (`frontend/wrapper.py`, `frontend/build_exe.py`,
  `frontend/requirements-build.txt`) — they aren't part of running the app.
