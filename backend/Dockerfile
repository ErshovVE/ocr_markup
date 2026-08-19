# Backend: OCR Consensus (спайк) — FastAPI + PaddleOCR/SuryaOCR/Tesseract.
# Собирать из корня репозитория: docker build -f backend/Dockerfile .
FROM python:3.12-slim

# tesseract-ocr-rus — системный языковой пакет, без него pytesseract lang="rus" падает.
# libgl1/libglib2.0-0 — рантайм-зависимости opencv-python на slim-образе.
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-rus \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend/ backend/

EXPOSE 8756

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8756"]
