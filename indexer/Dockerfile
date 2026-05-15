ARG BASE_IMAGE=python:3.12-slim
FROM ${BASE_IMAGE}

ENV PYTHONUNBUFFERED=1 \
    HF_HOME=/data/models \
    TRANSFORMERS_CACHE=/data/models

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates libjpeg62-turbo \
    && rm -rf /var/lib/apt/lists/*

COPY indexer/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir --no-deps "accelerate>=1.0"

COPY indexer/app ./app

EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
