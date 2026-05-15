from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any

import httpx

from .config import Settings
from .reviews import REVIEW_TAGS

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ReviewClassificationInput:
    asin: str
    review_id: str
    rating: int | None
    title: str | None
    text: str


@dataclass(frozen=True)
class ReviewTag:
    review_id: str
    tag: str
    confidence: float


class OpenRouterReviewClassifier:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client = httpx.AsyncClient(timeout=settings.http_timeout_seconds)

    async def close(self) -> None:
        await self._client.aclose()

    async def classify(
        self, reviews: list[ReviewClassificationInput]
    ) -> dict[str, list[ReviewTag]]:
        if not reviews:
            return {}
        if not self.settings.openrouter_api_key:
            raise ValueError("OPENROUTER_API_KEY is required for review classification")
        payload = self._payload(reviews)
        headers = {
            "Authorization": f"Bearer {self.settings.openrouter_api_key}",
            "Content-Type": "application/json",
        }
        if self.settings.openrouter_referer:
            headers["HTTP-Referer"] = self.settings.openrouter_referer
        if self.settings.openrouter_app_title:
            headers["X-Title"] = self.settings.openrouter_app_title

        last_error: Exception | None = None
        for attempt in range(self.settings.openrouter_max_retries + 1):
            try:
                response = await self._client.post(
                    f"{self.settings.openrouter_base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                )
                if response.status_code in {429, 500, 502, 503, 504}:
                    response.raise_for_status()
                response.raise_for_status()
                return self._parse_response(response.json())
            except Exception as exc:
                last_error = exc
                if attempt >= self.settings.openrouter_max_retries:
                    break
                await asyncio.sleep(min(2**attempt, 10))
        assert last_error is not None
        raise last_error

    def _payload(self, reviews: list[ReviewClassificationInput]) -> dict[str, Any]:
        review_rows = [
            {
                "review_id": review.review_id,
                "rating": review.rating,
                "title": review.title,
                "text": review.text,
            }
            for review in reviews
        ]
        return {
            "model": self.settings.openrouter_model,
            "temperature": 0,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Classify each Amazon product review into zero or more "
                        "allowed tags. Use only evidence in the review text. "
                        "Return confidence from 0 to 1. Do not invent tags."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {"allowed_tags": REVIEW_TAGS, "reviews": review_rows},
                        ensure_ascii=True,
                    ),
                },
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "review_tag_batch",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "reviews": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "additionalProperties": False,
                                    "properties": {
                                        "review_id": {"type": "string"},
                                        "tags": {
                                            "type": "array",
                                            "items": {
                                                "type": "object",
                                                "additionalProperties": False,
                                                "properties": {
                                                    "tag": {
                                                        "type": "string",
                                                        "enum": list(REVIEW_TAGS),
                                                    },
                                                    "confidence": {
                                                        "type": "number",
                                                        "minimum": 0,
                                                        "maximum": 1,
                                                    },
                                                },
                                                "required": ["tag", "confidence"],
                                            },
                                        },
                                    },
                                    "required": ["review_id", "tags"],
                                },
                            }
                        },
                        "required": ["reviews"],
                    },
                },
            },
        }

    def _parse_response(self, payload: dict[str, Any]) -> dict[str, list[ReviewTag]]:
        choices = payload.get("choices") or [{}]
        content = choices[0].get("message", {}).get("content", "")
        if isinstance(content, list):
            content = "".join(
                part.get("text", "") if isinstance(part, dict) else str(part)
                for part in content
            )
        parsed = json.loads(str(content))
        allowed = set(REVIEW_TAGS)
        out: dict[str, list[ReviewTag]] = {}
        for review in parsed.get("reviews", []):
            review_id = str(review.get("review_id") or "")
            if not review_id:
                continue
            tags: list[ReviewTag] = []
            seen: set[str] = set()
            for item in review.get("tags", []):
                tag = str(item.get("tag") or "")
                if tag not in allowed or tag in seen:
                    continue
                try:
                    confidence = float(item.get("confidence"))
                except (TypeError, ValueError):
                    continue
                confidence = max(0.0, min(1.0, confidence))
                tags.append(
                    ReviewTag(review_id=review_id, tag=tag, confidence=confidence)
                )
                seen.add(tag)
            out[review_id] = tags
        return out
