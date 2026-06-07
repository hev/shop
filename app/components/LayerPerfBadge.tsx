import type { LayerPerf } from "@/lib/backend";

const CACHE_TONE: Record<string, string> = {
  hit: "bg-emerald-50 text-emerald-900 ring-emerald-200",
  miss: "bg-amber-50 text-amber-900 ring-amber-200",
  "miss-on-error": "bg-red-50 text-red-900 ring-red-200",
};

function cacheTone(status: string | null): string {
  if (!status) return "bg-ink-50 text-ink-600 ring-ink-200";
  return CACHE_TONE[status] ?? "bg-ink-50 text-ink-700 ring-ink-200";
}

// Single Layer round-trip indicator. Renders either:
//   [42ms · cache hit]   ← cacheable endpoint, header present
//   [120ms]              ← query endpoint, no cache header
// Use `label` to disambiguate when multiple appear in one section.
export function LayerPerfBadge({
  perf,
  label,
  className = "",
}: {
  perf: LayerPerf | null | undefined;
  label?: string;
  className?: string;
}) {
  if (!perf) return null;
  const { latency_ms, cache_status } = perf;
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 font-mono text-[11px] leading-5 ring-1 ${cacheTone(
        cache_status,
      )} ${className}`}
      title={`Layer gateway round-trip${
        cache_status ? ` · x-layer-cache: ${cache_status}` : " · query (not cache-eligible)"
      }`}
    >
      {label ? <span className="font-sans text-ink-500">{label}</span> : null}
      <span className="tabular-nums">{latency_ms}ms</span>
      {cache_status ? (
        <>
          <span aria-hidden="true">·</span>
          <span>cache {cache_status}</span>
        </>
      ) : null}
    </span>
  );
}

function formatStableAsOf(epochMs: number): string {
  return new Date(epochMs).toISOString().replace("T", " ").slice(0, 16) + " UTC";
}

// Watermark line for query responses — shows the consistency snapshot
// the gateway pinned the result to. Renders nothing when absent (typical
// right after a deploy or a fresh namespace).
export function StableAsOfBadge({
  stableAsOf,
  isStable,
  className = "",
}: {
  stableAsOf: number | null | undefined;
  isStable?: boolean;
  className?: string;
}) {
  if (stableAsOf == null) return null;
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full bg-ink-50 px-2.5 py-0.5 font-mono text-[11px] leading-5 text-ink-700 ring-1 ring-ink-200 ${className}`}
      title="layer.stable_as_of — the consistent snapshot this result pins to"
    >
      <span className="font-sans text-ink-500">as of</span>
      <span className="tabular-nums">{formatStableAsOf(stableAsOf)}</span>
      {isStable === false ? (
        <span className="text-amber-700">· catching up</span>
      ) : null}
    </span>
  );
}
