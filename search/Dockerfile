ARG BASE_IMAGE=python:3.12-slim
FROM ${BASE_IMAGE}

ENV PYTHONUNBUFFERED=1 \
    HF_HOME=/opt/model-cache \
    TRANSFORMERS_CACHE=/opt/model-cache

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Pass the sibling SDK with BuildKit:
#   --build-context layer_client=../layer/clients/python
COPY --from=layer_client . /layer/clients/python
COPY common /common
COPY search/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Bake CLIP weights so cold starts don't pay an HF round-trip. Qwen-8B is
# off by default — the search pod doesn't load it on CPU (review search
# returns 503 unless API_REVIEW_SEARCH_ENABLED=true, which only fits on a
# GPU pod).
ARG BAKE_CLIP=true
ARG BAKE_QWEN=false
ARG CLIP_MODEL=openai/clip-vit-large-patch14
ARG REVIEW_MODEL=Qwen/Qwen3-Embedding-8B
RUN if [ "$BAKE_CLIP" = "true" ]; then \
      python -c "from huggingface_hub import snapshot_download; \
snapshot_download('${CLIP_MODEL}', cache_dir='${HF_HOME}')" ; \
    fi && \
    if [ "$BAKE_QWEN" = "true" ]; then \
      python -c "from huggingface_hub import snapshot_download; \
snapshot_download('${REVIEW_MODEL}', cache_dir='${HF_HOME}')" ; \
    fi

COPY search/app ./app

EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
