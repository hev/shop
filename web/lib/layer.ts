const GATEWAY_URL = process.env.LAYER_GATEWAY_URL ?? "";
const PRODUCT_NAMESPACE = process.env.LAYER_PRODUCT_NAMESPACE ?? "amazon-products";
const REVIEW_NAMESPACE_BASE = process.env.LAYER_REVIEW_NAMESPACE_BASE ?? "v2-amazon-reviews";
// Read-side override — mirrors REVIEWS_QUERY_NAMESPACE_BASE on the indexer
// side so cache warms hit the namespace the API actually queries during a
// hot-swap migration. Falls back to REVIEW_NAMESPACE_BASE when unset.
const REVIEW_QUERY_NAMESPACE_BASE =
  process.env.LAYER_REVIEW_QUERY_NAMESPACE_BASE || REVIEW_NAMESPACE_BASE;
const REVIEW_SHARD_COUNT = Number(process.env.LAYER_REVIEW_SHARD_COUNT ?? "16");

const WARM_TIMEOUT_MS = 4_000;

let warmKicked = false;

export function layerWarmEnabled(): boolean {
  return GATEWAY_URL.length > 0;
}

function warmNamespaces(): string[] {
  const out = [PRODUCT_NAMESPACE];
  for (let i = 0; i < REVIEW_SHARD_COUNT; i++) {
    out.push(`${REVIEW_QUERY_NAMESPACE_BASE}-${i}`);
  }
  return out;
}

async function warmOne(namespace: string): Promise<void> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), WARM_TIMEOUT_MS);
  try {
    const res = await fetch(`${GATEWAY_URL}/v2/namespaces/${namespace}/warm`, {
      method: "POST",
      signal: controller.signal,
    });
    if (!res.ok) {
      console.warn(`[layer warm] ${namespace} → ${res.status}`);
    }
  } catch (err) {
    console.warn(`[layer warm] ${namespace} failed:`, err);
  } finally {
    clearTimeout(timeout);
  }
}

// Fire a one-shot cache warm for the product namespace + every review shard.
// Subsequent calls in the same pod are no-ops. Returns immediately; the warms
// run in the background and the gateway de-dupes concurrent warms per namespace.
export function warmOnce(): void {
  if (warmKicked || !layerWarmEnabled()) return;
  warmKicked = true;
  for (const ns of warmNamespaces()) {
    void warmOne(ns);
  }
}
