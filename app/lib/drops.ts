import {
  backendDrops,
  backendEnabled,
  type DropInfo,
  type DropsResult,
} from "./backend";

export type { DropInfo, DropsResult };

// The nightly reindex CronJob fires at 02:00 UTC (launch-plan WS4). The
// countdown and the mock ledger are both anchored to this hour.
export const DROP_HOUR_UTC = 2;

// New products per drop — the ops knob. In production this is the nightly
// CronJob's row count against the Amazon dataset (chart value); the demo
// ledger mirrors it so the storefront always reflects the configured size.
export const DROP_SIZE = (() => {
  const n = Number(process.env.HEV_SHOP_DROP_SIZE);
  return Number.isFinite(n) && n > 0 ? Math.floor(n) : 10_000;
})();

export function nextDropAtMs(now: number): number {
  const d = new Date(now);
  const tonight = Date.UTC(
    d.getUTCFullYear(),
    d.getUTCMonth(),
    d.getUTCDate(),
    DROP_HOUR_UTC,
  );
  return tonight > now ? tonight : tonight + 86_400_000;
}

export function dropDate(drop: DropInfo): Date | null {
  const m = /^catalog-(\d{4})-(\d{2})-(\d{2})$/.exec(drop.run_id);
  if (!m) return null;
  return new Date(Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3])));
}

// Deterministic per-run hash — used to vary mock details (drain times, demo
// product slices) night to night without Math.random hydration drift.
export function dropSeed(s: string): number {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) % 997;
  return h;
}

function mockDrops(now: number, days = 7): DropInfo[] {
  const out: DropInfo[] = [];
  // The most recent drop is last night's run (or tonight's, if it already
  // fired) — one day before whatever the *next* drop is.
  let at = nextDropAtMs(now) - 86_400_000;
  for (let i = 0; i < days; i++) {
    const iso = new Date(at).toISOString().slice(0, 10);
    const h = dropSeed(iso);
    out.push({
      run_id: `catalog-${iso}`,
      product_count: DROP_SIZE,
      // Workers drain a few minutes after the CronJob fires.
      stable_as_of: at + (4 + (h % 11)) * 60_000,
    });
    at -= 86_400_000;
  }
  return out;
}

// Demo mode always has a ledger; a live backend either answers /drops or the
// drop surfaces hide entirely (no empty-state placeholders on the homepage).
export async function getDrops(): Promise<DropsResult | null> {
  if (!backendEnabled()) {
    return { drops: mockDrops(Date.now()), layer_perf: null };
  }
  try {
    const result = await backendDrops();
    return result.drops.length > 0 ? result : null;
  } catch {
    return null;
  }
}
