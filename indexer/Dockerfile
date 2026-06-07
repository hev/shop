ARG BASE_IMAGE=python:3.12-slim
FROM ${BASE_IMAGE} AS base

ENV PYTHONUNBUFFERED=1 \
    HF_HOME=/opt/model-cache \
    TRANSFORMERS_CACHE=/opt/model-cache

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates libjpeg62-turbo \
    && rm -rf /var/lib/apt/lists/*

# Pass the sibling SDK with BuildKit:
#   --build-context layer_client=../layer/clients/python
COPY --from=layer_client . /layer/clients/python
COPY common /common
COPY indexer/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY indexer/*.py ./

EXPOSE 8080

# Control plane (/index, /status). No models load here.
FROM base AS api
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]

# CPU extraction worker — pipelines/extract-chunk.yaml. No CLIP needed.
FROM base AS extract-chunk
CMD ["python", "extract_chunk.py"]

# GPU embedding worker — pipelines/embed.yaml. Bake CLIP weights into the
# image so cold starts on autoscaled pods don't pay the HF round-trip.
FROM base AS embed
ARG CLIP_MODEL=openai/clip-vit-large-patch14
RUN python -c "from huggingface_hub import snapshot_download; \
snapshot_download('${CLIP_MODEL}', cache_dir='${HF_HOME}')"
ENV MODEL_CACHE_DIR=/opt/model-cache
CMD ["python", "embed.py"]
