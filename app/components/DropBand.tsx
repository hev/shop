import Link from "next/link";
import { getDrops } from "@/lib/drops";
import { DropCountdown } from "./DropCountdown";

// Slim dark strip under the hero announcing last night's catalog run.
// Renders nothing when /drops is unavailable — no empty-state placeholder.
export async function DropBand() {
  const result = await getDrops();
  const latest = result?.drops[0];
  if (!latest) return null;

  return (
    <section className="border-b border-ink-200 bg-ink-900 text-ink-100">
      <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-x-4 gap-y-1 px-4 py-2.5 text-xs">
        <span className="relative flex h-2 w-2">
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-accent opacity-60" />
          <span className="relative inline-flex h-2 w-2 rounded-full bg-accent" />
        </span>
        <span className="font-semibold uppercase tracking-widest text-accent-soft">
          Daily drop
        </span>
        <span className="font-mono">{latest.run_id}</span>
        <span className="hidden text-ink-300 md:inline">
          {latest.product_count.toLocaleString()} new products, indexed while
          you slept
        </span>
        <span className="hidden items-baseline gap-1.5 text-ink-300 lg:inline-flex">
          · next drop in{" "}
          <DropCountdown className="font-mono tabular-nums text-ink-100" />
        </span>
        <Link
          href="/drops"
          className="ml-auto shrink-0 font-medium underline-offset-2 hover:underline"
        >
          shop the drop →
        </Link>
      </div>
    </section>
  );
}
