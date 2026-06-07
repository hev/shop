ARG BASE_IMAGE=python:3.12-slim
FROM ${BASE_IMAGE}

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

# Pre-download model weights into the image so cold starts on autoscaled
# pods don't pay the HF round-trip.
ARG BAKE_CLIP=true
ARG CLIP_MODEL=openai/clip-vit-large-patch14
RUN if [ "$BAKE_CLIP" = "true" ]; then \
      python -c "from huggingface_hub import snapshot_download; \
snapshot_download('${CLIP_MODEL}', cache_dir='${HF_HOME}')" ; \
    fi

COPY indexer/app ./app

EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
