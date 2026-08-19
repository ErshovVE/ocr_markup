# Frontend: Streamlit-инструмент разметки OCR (app.py + src/)
# Собирать из корня репозитория: docker build -f frontend/Dockerfile .
FROM python:3.12-slim

WORKDIR /app

COPY frontend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY frontend/app.py .
COPY frontend/src/ src/

EXPOSE 8501

ENTRYPOINT ["streamlit", "run", "app.py", \
    "--server.address=0.0.0.0", \
    "--server.enableXsrfProtection=false"]
