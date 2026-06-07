"""Lazy model wrappers shared across hev-shop services."""

from __future__ import annotations

from io import BytesIO
from typing import Any

from .config import Settings


class CLIPImageEmbedder:
    def __init__(self, settings: Settings) -> None:
        import numpy as np
        import torch
        from transformers import CLIPModel

        self._np = np
        self._torch = torch
        if settings.clip_device == "auto":
            self.device = "cuda" if torch.cuda.is_available() else "cpu"
        else:
            self.device = settings.clip_device

        self.model = CLIPModel.from_pretrained(
            settings.clip_model_name, cache_dir=str(settings.model_cache_dir)
        )
        self.model.to(self.device)
        self.model.eval()
        self.image_size = 224
        self.image_mean = torch.tensor([0.48145466, 0.4578275, 0.40821073])
        self.image_std = torch.tensor([0.26862954, 0.26130258, 0.27577711])

    def _preprocess_image(self, image: Any):
        from PIL import Image

        image = image.convert("RGB")
        width, height = image.size
        scale = self.image_size / min(width, height)
        resized = (
            max(self.image_size, round(width * scale)),
            max(self.image_size, round(height * scale)),
        )
        image = image.resize(resized, Image.Resampling.BICUBIC)
        left = (image.width - self.image_size) // 2
        top = (image.height - self.image_size) // 2
        image = image.crop((left, top, left + self.image_size, top + self.image_size))

        array = self._np.asarray(image, dtype=self._np.float32) / 255.0
        tensor = self._torch.from_numpy(array).permute(2, 0, 1)
        return (tensor - self.image_mean[:, None, None]) / self.image_std[:, None, None]

    def encode_image_bytes(self, images: list[bytes]) -> list[list[float]]:
        from PIL import Image

        tensors = []
        for raw in images:
            with Image.open(BytesIO(raw)) as image:
                tensors.append(self._preprocess_image(image))

        inputs = {"pixel_values": self._torch.stack(tensors).to(self.device)}
        with self._torch.inference_mode():
            features = self.model.get_image_features(**inputs)
            if not isinstance(features, self._torch.Tensor):
                features = features.pooler_output
            features = features / features.norm(p=2, dim=-1, keepdim=True)
        return features.cpu().float().tolist()


class CLIPTextEmbedder:
    def __init__(self, settings: Settings) -> None:
        import torch
        from transformers import CLIPModel, CLIPTokenizer

        self._torch = torch
        if settings.clip_device == "auto":
            self.device = "cuda" if torch.cuda.is_available() else "cpu"
        else:
            self.device = settings.clip_device

        self.tokenizer = CLIPTokenizer.from_pretrained(
            settings.clip_model_name, cache_dir=str(settings.model_cache_dir)
        )
        self.model = CLIPModel.from_pretrained(
            settings.clip_model_name, cache_dir=str(settings.model_cache_dir)
        )
        self.model.to(self.device)
        self.model.eval()

    def encode_text(self, text: str) -> list[float]:
        inputs = self.tokenizer(
            text=[text], return_tensors="pt", padding=True, truncation=True
        )
        inputs = {key: value.to(self.device) for key, value in inputs.items()}
        with self._torch.inference_mode():
            features = self.model.get_text_features(**inputs)
            if not isinstance(features, self._torch.Tensor):
                features = features.pooler_output
            features = features / features.norm(p=2, dim=-1, keepdim=True)
        return features[0].cpu().float().tolist()
