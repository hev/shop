const GATEWAY_URL = process.env.LAYER_GATEWAY_URL ?? "";
const GATEWAY_API_KEY = (process.env.LAYER_GATEWAY_API_KEY ?? "").trim();
const PRODUCT_NAMESPACE = process.env.LAYER_PRODUCT_NAMESPACE ?? "amazon-products";

const WARM_TIMEOUT_MS = 4_000;

let warmKicked = false;

export function layerWarmEnabled(): boolean {
  return GATEWAY_URL.length > 0;
}

function warmNamespaces(): string[] {
  return [PRODUCT_NAMESPACE];
}

async function warmOne(namespace: string): Promise<void> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), WARM_TIMEOUT_MS);
  try {
    const res = await fetch(`${GATEWAY_URL}/v2/namespaces/${namespace}/warm`, {
      method: "POST",
      headers: GATEWAY_API_KEY ? { Authorization: `Bearer ${GATEWAY_API_KEY}` } : undefined,
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

// Fire a one-shot cache warm for the product namespace. Subsequent calls in the
// same pod are no-ops. Returns immediately; the gateway de-dupes concurrent
// warms per namespace.
export function warmOnce(): void {
  if (warmKicked || !layerWarmEnabled()) return;
  warmKicked = true;
  for (const ns of warmNamespaces()) {
    void warmOne(ns);
  }
}
