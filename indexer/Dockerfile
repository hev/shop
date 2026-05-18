ARG BASE_IMAGE=python:3.12-slim
FROM ${BASE_IMAGE}

ENV PYTHONUNBUFFERED=1 \
    HF_HOME=/opt/model-cache \
    TRANSFORMERS_CACHE=/opt/model-cache

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates libjpeg62-turbo \
    && rm -rf /var/lib/apt/lists/*

COPY indexer/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir --no-deps "accelerate>=1.0"

# Pre-download model weights into the image so cold starts on autoscaled
# pods (api, gpu, review-embed) don't pay the HF round-trip. The 8B Qwen
# bumps image size ~16 GB but eliminates the multi-minute HF pull that
# was killing the API on liveness-probe timeout.
ARG BAKE_MODELS=true
ARG CLIP_MODEL=openai/clip-vit-large-patch14
ARG REVIEW_MODEL=Qwen/Qwen3-Embedding-8B
RUN if [ "$BAKE_MODELS" = "true" ]; then \
      python -c "from huggingface_hub import snapshot_download; \
snapshot_download('${CLIP_MODEL}', cache_dir='${HF_HOME}'); \
snapshot_download('${REVIEW_MODEL}', cache_dir='${HF_HOME}')" ; \
    fi

COPY indexer/app ./app

EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
