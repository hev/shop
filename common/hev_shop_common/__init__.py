"""Shared library for the hev-shop search API and indexer workers.

Exposes three modules:

- `config` — Settings (BaseSettings) with every env var the services read.
- `records` — Product dataclasses and vector-attribute helpers shared between
  API request handling and worker pipelines.
- `embedders` — Lazy-init wrappers around CLIP image and text models.

Anything that knows about HTTP request/response shape lives in the
individual services, not here.
"""
