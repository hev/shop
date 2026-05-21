"""Shared library for the hev-shop search API and indexer workers.

Exposes three modules:

- `config` — Settings (BaseSettings) with every env var the services read.
- `records` — In-memory dataclasses + namespace/shard helpers + input
  normalizers shared between API request handling and worker pipelines.
- `embedders` — Lazy-init wrappers around CLIP-image / CLIP-text /
  Qwen-text. Search instantiates only the text variants; workers
  instantiate the image variant and (on GPU pods) Qwen.

Anything that knows about HTTP request/response shape lives in the
individual services, not here.
"""
