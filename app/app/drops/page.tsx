import type { Metadata } from "next";
import Link from "next/link";
import { LayerPerfBadge } from "@/components/LayerPerfBadge";
import { DropCountdown } from "@/components/DropCountdown";
import { dropDate, getDrops, DROP_HOUR_UTC, DROP_SIZE } from "@/lib/drops";
import type { DropInfo } from "@/lib/drops";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "hev·shop — daily drops",
  description:
    "Every night the pipeline indexes a fresh slice of the Amazon dataset. Each drop is one catalog run — new products, nightly.",
};

const WEEKDAY = new Intl.DateTimeFormat("en-US", {
  weekday: "long",
  timeZone: "UTC",
});
const MONTH = new Intl.DateTimeFormat("en-US", {
  month: "short",
  timeZone: "UTC",
});

function stableTime(epochMs: number | null): string | null {
  if (epochMs === null) return null;
  return new Date(epochMs).toISOString().slice(11, 16) + " UTC";
}

function DropRow({ drop, index }: { drop: DropInfo; index: number }) {
  const date = dropDate(drop);
  const latest = index === 0;
  const stable = stableTime(drop.stable_as_of);
  return (
    <Link
      href={`/search?drop=${encodeURIComponent(drop.run_id)}`}
      className={`group flex flex-wrap items-center gap-x-6 gap-y-2 rounded-2xl bg-white p-5 ring-1 transition sm:flex-nowrap ${
        latest
          ? "ring-2 ring-accent shadow-card"
          : "ring-ink-200 hover:ring-ink-900"
      }`}
      style={latest ? undefined : { opacity: Math.max(0.6, 1 - index * 0.07) }}
    >
      {/* date block */}
      <div className="flex w-24 shrink-0 items-baseline gap-2">
        <span className="font-display text-5xl leading-none tracking-tight text-ink-900">
          {date ? String(date.getUTCDate()).padStart(2, "0") : "··"}
        </span>
        <span className="text-xs font-semibold uppercase tracking-widest text-ink-500">
          {date ? MONTH.format(date) : ""}
        </span>
      </div>

      {/* run identity */}
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-mono text-sm text-ink-900">{drop.run_id}</span>
          {latest ? (
            <span className="inline-flex items-center gap-1.5 rounded-full bg-accent px-2.5 py-0.5 text-[10px] font-semibold uppercase tracking-widest text-white">
              <span className="relative flex h-1.5 w-1.5">
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-white opacity-70" />
                <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-white" />
              </span>
              Just dropped
            </span>
          ) : null}
        </div>
        <div className="mt-1 text-xs text-ink-500">
          {date ? `${WEEKDAY.format(date)} run` : "catalog run"}
          {stable ? (
            <>
              {" "}
              · namespace stable by{" "}
              <span className="font-mono">{stable}</span>
            </>
          ) : null}
        </div>
      </div>

      {/* count */}
      <div className="shrink-0 text-right">
        <div className="font-display text-2xl tracking-tight text-ink-900">
          {drop.product_count.toLocaleString()}
        </div>
        <div className="text-xs text-ink-500">new products</div>
      </div>

      <span
        aria-hidden
        className="hidden shrink-0 text-ink-300 transition group-hover:translate-x-1 group-hover:text-ink-900 sm:inline"
      >
        →
      </span>
    </Link>
  );
}

export default async function DropsPage() {
  const result = await getDrops();
  const drops = result?.drops ?? [];

  return (
    <div className="mx-auto max-w-7xl px-4 py-10">
      {/* masthead */}
      <div className="mb-10 grid grid-cols-1 gap-8 lg:grid-cols-[1fr_auto] lg:items-end">
        <div>
          <div className="flex items-center gap-3">
            <span className="text-xs font-semibold uppercase tracking-widest text-accent">
              Drops
            </span>
            <LayerPerfBadge perf={result?.layer_perf ?? null} label="/drops" />
          </div>
          <h1 className="mt-2 font-display text-5xl leading-[1.05] tracking-tight text-ink-900">
            Fresh vectors, nightly.
          </h1>
          <p className="mt-4 max-w-lg text-base text-ink-700">
            Every night at{" "}
            <span className="font-mono text-sm">
              {String(DROP_HOUR_UTC).padStart(2, "0")}:00 UTC
            </span>{" "}
            the pipeline pulls the next{" "}
            <span className="font-mono text-sm">
              {DROP_SIZE.toLocaleString()}
            </span>{" "}
            products from the Amazon dataset, embeds them, and stamps each one
            with a <span className="font-mono text-sm">catalog_run_id</span>.
            Each drop below is one run — the products that joined the index
            that night. The shelves don't restock; they grow.
          </p>
        </div>

        {/* countdown card */}
        <div className="w-full rounded-2xl bg-ink-900 p-6 text-ink-100 lg:w-72">
          <div className="text-xs font-semibold uppercase tracking-widest text-accent-soft">
            Next drop in
          </div>
          <DropCountdown className="mt-2 block font-mono text-4xl tabular-nums tracking-tight" />
          <div className="mt-2 text-xs text-ink-300">
            nightly · {String(DROP_HOUR_UTC).padStart(2, "0")}:00 UTC · CronJob
            does not sleep
          </div>
        </div>
      </div>

      {/* ledger */}
      {drops.length > 0 ? (
        <div className="flex flex-col gap-3">
          {drops.map((drop, i) => (
            <DropRow key={drop.run_id} drop={drop} index={i} />
          ))}
        </div>
      ) : (
        <div className="rounded-2xl border border-dashed border-ink-200 bg-white p-12 text-center">
          <p className="font-display text-2xl tracking-tight">
            No drops on the ledger yet.
          </p>
          <p className="mt-2 text-sm text-ink-500">
            The pipeline drops nightly at{" "}
            {String(DROP_HOUR_UTC).padStart(2, "0")}:00 UTC. Check back after
            the next run, or{" "}
            <Link href="/" className="underline">
              browse the current index
            </Link>
            .
          </p>
        </div>
      )}

      <p className="mt-10 text-xs text-ink-500">
        Run markers are app-owned attributes stamped on each product vector
        during the nightly ingest; completed runs are read back through Layer
        namespace snapshots. See{" "}
        <a
          href="https://hevlayer.com/docs/api/snapshots"
          className="font-medium text-ink-700 underline-offset-2 hover:underline"
        >
          snapshot history
        </a>{" "}
        in the hev layer docs.
      </p>
    </div>
  );
}
