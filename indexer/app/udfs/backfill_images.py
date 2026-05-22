"""backfill-images UDF — populates the `image` blob on existing product rows.

Runs the Layer UDF contract (RFC 0004): the gateway scans the
`amazon-products` namespace for rows missing the image blob, hands each
`(id, image_url)` pair to this function, and writes the returned bytes into
the Aerospike doc cache (blob storage, no tpuf write).

Run locally:

    HEVLAYER_BASE_URL=http://127.0.0.1:8080 \\
    HEVLAYER_UDF_ID=hev-shop-backfill-images \\
    python -m app.udfs.backfill_images
"""

from __future__ import annotations

import asyncio
import logging
import os

import httpx
from hevlayer.udf import Blob, PermanentError, TransientError, run_udf_worker, udf

logger = logging.getLogger(__name__)


UDF_ID = os.environ.get("HEVLAYER_UDF_ID", "hev-shop-backfill-images")
BLOB_MAX_BYTES = int(os.environ.get("BLOB_MAX_BYTES", str(512 * 1024)))
FETCH_TIMEOUT_SECONDS = float(os.environ.get("BACKFILL_FETCH_TIMEOUT_SECONDS", "10"))
USER_AGENT = os.environ.get("BACKFILL_USER_AGENT", "hev-shop-backfill-images/1.0")

# httpx client lives at module scope so connections are pooled across the
# per-batch dispatch calls the SDK makes against this function.
_client = httpx.Client(
    timeout=FETCH_TIMEOUT_SECONDS,
    follow_redirects=True,
    headers={"User-Agent": USER_AGENT},
)


@udf(
    inputs=["id", "image_url"],
    output="image",
    kind="blob",
    batch_size=16,
)
def fetch_image(*, id: str, image_url: str) -> Blob:
    if not image_url:
        raise PermanentError(f"{id}: image_url is empty")

    try:
        response = _client.get(image_url)
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        # 4xx (except 408/429) means the URL is wrong or gone — no point
        # retrying. Everything else (5xx, 408, 429) is treated as a transient
        # CDN/network blip and retried with exponential backoff.
        if 400 <= status < 500 and status not in (408, 429):
            raise PermanentError(f"{id}: {status} fetching {image_url}") from exc
        raise TransientError(f"{id}: {status} fetching {image_url}") from exc
    except (httpx.TimeoutException, httpx.TransportError) as exc:
        raise TransientError(f"{id}: {exc.__class__.__name__} fetching {image_url}") from exc

    content_type = (response.headers.get("content-type") or "").split(";", 1)[0].strip()
    if not content_type.startswith("image/"):
        raise PermanentError(f"{id}: non-image content-type {content_type!r}")

    body = response.content
    if len(body) > BLOB_MAX_BYTES:
        raise PermanentError(
            f"{id}: {len(body)} bytes exceeds BLOB_MAX_BYTES={BLOB_MAX_BYTES}"
        )

    return Blob(data=body, content_type=content_type)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_udf_worker(fetch_image, udf_id=UDF_ID))


if __name__ == "__main__":
    main()
