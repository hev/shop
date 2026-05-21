"""Model wrappers shared across the hev-shop services.

The CLIP/Qwen instantiation is heavy (torch + transformers), so each class
imports those lazily inside `__init__`. Callers construct one instance per
process behind a lazy singleton — see `indexer/app/pipeline.py` (image +
Qwen for stage workers) and `search/app/main.py` (CLIP-text + Qwen for
the read API).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .config import Settings


class CLIPImageEmbedder:
    def __init__(self, settings: Settings) -> None:
        import torch
        from transformers import CLIPModel, CLIPProcessor

        self._torch = torch
        if settings.clip_device == "auto":
            self.device = "cuda" if torch.cuda.is_available() else "cpu"
        else:
            self.device = settings.clip_device

        self.processor = CLIPProcessor.from_pretrained(
            settings.clip_model_name, cache_dir=str(settings.model_cache_dir)
        )
        self.model = CLIPModel.from_pretrained(
            settings.clip_model_name, cache_dir=str(settings.model_cache_dir)
        )
        self.model.to(self.device)
        self.model.eval()

    def encode_image_paths(self, paths: list[Path]) -> list[list[float]]:
        from PIL import Image

        images = []
        for path in paths:
            with Image.open(path) as image:
                images.append(image.convert("RGB").copy())

        inputs = self.processor(images=images, return_tensors="pt")
        inputs = {key: value.to(self.device) for key, value in inputs.items()}
        with self._torch.inference_mode():
            features = self.model.get_image_features(**inputs)
            if not isinstance(features, self._torch.Tensor):
                features = features.pooler_output
            features = features / features.norm(p=2, dim=-1, keepdim=True)
        return features.cpu().float().tolist()


class CLIPTextEmbedder:
    def __init__(self, settings: Settings) -> None:
        import torch
        from transformers import CLIPModel, CLIPProcessor

        self._torch = torch
        if settings.clip_device == "auto":
            self.device = "cuda" if torch.cuda.is_available() else "cpu"
        else:
            self.device = settings.clip_device

        self.processor = CLIPProcessor.from_pretrained(
            settings.clip_model_name, cache_dir=str(settings.model_cache_dir)
        )
        self.model = CLIPModel.from_pretrained(
            settings.clip_model_name, cache_dir=str(settings.model_cache_dir)
        )
        self.model.to(self.device)
        self.model.eval()

    def encode_text(self, text: str) -> list[float]:
        inputs = self.processor(
            text=[text], return_tensors="pt", padding=True, truncation=True
        )
        inputs = {key: value.to(self.device) for key, value in inputs.items()}
        with self._torch.inference_mode():
            features = self.model.get_text_features(**inputs)
            if not isinstance(features, self._torch.Tensor):
                features = features.pooler_output
            features = features / features.norm(p=2, dim=-1, keepdim=True)
        return features[0].cpu().float().tolist()


class QwenTextEmbedder:
    def __init__(self, settings: Settings) -> None:
        import torch
        from transformers import AutoModel, AutoTokenizer

        self._torch = torch
        if settings.review_embedding_device == "auto":
            self.device = "cuda" if torch.cuda.is_available() else "cpu"
        else:
            self.device = settings.review_embedding_device

        self.tokenizer = AutoTokenizer.from_pretrained(
            settings.review_embedding_model_name,
            cache_dir=str(settings.model_cache_dir),
        )
        model_kwargs: dict[str, Any] = {}
        if str(self.device).startswith("cuda"):
            model_kwargs["torch_dtype"] = torch.float16
            model_kwargs["low_cpu_mem_usage"] = True
            model_kwargs["device_map"] = {"": self.device}
        self.model = AutoModel.from_pretrained(
            settings.review_embedding_model_name,
            cache_dir=str(settings.model_cache_dir),
            **model_kwargs,
        )
        if "device_map" not in model_kwargs:
            self.model.to(self.device)
        self.model.eval()

    def chunk_text(
        self, text: str, *, chunk_tokens: int, chunk_overlap: int
    ) -> list[str]:
        if chunk_tokens <= 0:
            raise ValueError("chunk_tokens must be positive")
        if chunk_overlap < 0 or chunk_overlap >= chunk_tokens:
            raise ValueError("chunk_overlap must be non-negative and less than chunk_tokens")
        token_ids = self.tokenizer.encode(text, add_special_tokens=False)
        if not token_ids:
            return []
        chunks: list[str] = []
        step = chunk_tokens - chunk_overlap
        for start in range(0, len(token_ids), step):
            window = token_ids[start : start + chunk_tokens]
            if not window:
                continue
            chunk = self.tokenizer.decode(window, skip_special_tokens=True).strip()
            if chunk:
                chunks.append(chunk)
            if start + chunk_tokens >= len(token_ids):
                break
        return chunks

    def encode_texts(self, texts: list[str]) -> list[list[float]]:
        inputs = self.tokenizer(
            texts,
            return_tensors="pt",
            padding=True,
            truncation=True,
            max_length=8192,
        )
        inputs = {key: value.to(self.device) for key, value in inputs.items()}
        with self._torch.inference_mode():
            outputs = self.model(**inputs)
            hidden = outputs.last_hidden_state
            mask = inputs["attention_mask"].unsqueeze(-1).expand(hidden.size()).float()
            summed = (hidden * mask).sum(dim=1)
            counts = mask.sum(dim=1).clamp(min=1e-9)
            features = summed / counts
            features = features / features.norm(p=2, dim=-1, keepdim=True)
        return features.cpu().float().tolist()
