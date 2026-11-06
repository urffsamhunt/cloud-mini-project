FROM python:3.12.16-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1 HF_HUB_OFFLINE=1 HF_HOME=/tmp/hf
WORKDIR /app
COPY service/requirements.txt .
RUN pip install -r requirements.txt
COPY service/app.py .
COPY training/common.py .
COPY data/schema.json .
RUN useradd --uid 10001 --no-create-home app
USER app
EXPOSE 8000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
