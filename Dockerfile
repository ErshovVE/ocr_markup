# Frontend: Streamlit-инструмент разметки OCR (app1.py + src/)
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app1.py .
COPY src/ src/

EXPOSE 8501

ENTRYPOINT ["streamlit", "run", "app1.py", \
    "--server.address=0.0.0.0", \
    "--server.enableXsrfProtection=false"]
