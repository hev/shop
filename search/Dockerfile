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
# CPU-only torch: the search service embeds CLIP-text on the CPU system node and
# never touches a GPU, so install torch from the CPU wheel index to skip the
# ~5GB of nvidia CUDA libraries the default wheel bundles. This must precede the
# requirements install so transformers binds to the CPU build already present.
RUN pip install --no-cache-dir "torch>=2.5" --index-url https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir -r requirements.txt

# Bake CLIP weights so cold starts don't pay an HF round-trip. Fetch only the
# config, tokenizer, and safetensors weights: an unfiltered snapshot_download
# also pulls pytorch_model.bin + the TF/Flax weights, which transformers never
# uses when safetensors is present and which roughly triple the baked size.
# Then load the text path offline so a missing file fails the build here rather
# than the search pod's readiness probe in prod.
ARG BAKE_CLIP=true
ARG CLIP_MODEL=openai/clip-vit-large-patch14
RUN if [ "$BAKE_CLIP" = "true" ]; then \
      python -c "from huggingface_hub import snapshot_download; \
snapshot_download('${CLIP_MODEL}', cache_dir='${HF_HOME}', allow_patterns=['*.json','*.txt','*.safetensors'])" && \
      HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 python -c "from transformers import CLIPModel, CLIPTokenizer; \
CLIPTokenizer.from_pretrained('${CLIP_MODEL}', cache_dir='${HF_HOME}'); \
CLIPModel.from_pretrained('${CLIP_MODEL}', cache_dir='${HF_HOME}'); print('CLIP text path loads OK')" ; \
    fi

COPY search/*.py ./

EXPOSE 8080
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]
