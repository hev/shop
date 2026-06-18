from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from huggingface_source import (
    HuggingFaceSource,
    metadata_url,
    resolve_source,
    safe_cache_token,
)

from _fakes import make_settings


class HuggingFaceSourceTests(unittest.TestCase):
    def test_metadata_url_uses_endpoint_revision_and_config(self) -> None:
        self.assertEqual(
            metadata_url(
                endpoint="https://hf.internal/",
                repo="McAuley-Lab/Amazon-Reviews-2023",
                config="raw_meta_Cell_Phones",
                revision="abc123",
            ),
            "https://hf.internal/datasets/McAuley-Lab/Amazon-Reviews-2023/resolve/abc123/raw/meta_categories/meta_Cell_Phones.jsonl",
        )

    def test_source_cache_name_includes_safe_revision(self) -> None:
        source = HuggingFaceSource(
            endpoint="https://huggingface.co",
            repo="repo",
            config="raw_meta_Electronics",
            revision="feature/test",
        )

        self.assertEqual(safe_cache_token("feature/test"), "feature_test")
        self.assertEqual(source.cache_name, "meta_Electronics.feature_test.jsonl")

    def test_resolve_source_uses_injected_warehouse_and_source_ref(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            token_path = Path(tmp) / "token"
            token_path.write_text("hf_token\n", encoding="utf-8")
            with patch.dict(
                "os.environ",
                {
                    "HEVLAYER_WAREHOUSE": json.dumps(
                        {
                            "kind": "huggingface",
                            "endpoint": "https://hf.internal",
                            "repo": "warehouse/repo",
                            "tokenPath": str(token_path),
                        }
                    ),
                    "HEVLAYER_SOURCE_REF": json.dumps(
                        {
                            "kind": "huggingface",
                            "repo": "source/repo",
                            "config": "raw_meta_Electronics",
                            "revision": "abc123",
                        }
                    ),
            },
            clear=False,
        ):
                source = resolve_source(
                    make_settings(hf_dataset="fallback/repo"), "Appliances"
                )

        self.assertEqual(source.endpoint, "https://hf.internal")
        self.assertEqual(source.repo, "source/repo")
        self.assertEqual(source.config, "raw_meta_Electronics")
        self.assertEqual(source.revision, "abc123")
        self.assertEqual(source.token, "hf_token")

    def test_resolve_source_falls_back_to_settings(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "HEVLAYER_WAREHOUSE": "",
                "HEVLAYER_SOURCE_REF": "",
            },
            clear=False,
        ):
            source = resolve_source(
                make_settings(hf_dataset="fallback/repo", hf_token="settings-token"),
                "Cell Phones",
            )

        self.assertEqual(source.endpoint, "https://huggingface.co")
        self.assertEqual(source.repo, "fallback/repo")
        self.assertEqual(source.config, "raw_meta_Cell_Phones")
        self.assertEqual(source.revision, "main")
        self.assertEqual(source.token, "settings-token")
