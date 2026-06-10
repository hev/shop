"use client";

import { useEffect, useId, useRef, useState } from "react";
import { getFeatureExplainer } from "@/lib/feature-explainers";

// Reusable "How it works" affordance for any Layer-powered result set. Drop
//   <FeatureExplainer id="browsing-rail" />
// next to a section header; content comes from the registry in
// `lib/feature-explainers.ts`. A labeled pill opens a popover with a
// plain-language summary, the mechanism, an optional gateway call shape, and
// links to the docs.
//
// Client component: it owns popover open/close, outside-click, and Esc.
export function FeatureExplainer({
  id,
  stat,
  align = "right",
  className = "",
}: {
  id: string;
  // Optional live, per-instance line shown atop the popover body (e.g. the
  // browsing rail's "3 queries → RRF → 8 results"). Static copy stays in the
  // registry; only the runtime number comes through here.
  stat?: string;
  // Which edge of the trigger the popover aligns to, so it never overflows the
  // viewport. Headers on the right use "right"; left-aligned kickers use "left".
  align?: "left" | "right";
  className?: string;
}) {
  const content = getFeatureExplainer(id);
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const panelId = useId();

  useEffect(() => {
    if (!open) return;
    function onDown(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  if (!content) return null;

  return (
    <div ref={ref} className={`relative inline-flex ${className}`}>
      <button
        type="button"
        aria-expanded={open}
        aria-haspopup="dialog"
        aria-controls={open ? panelId : undefined}
        onClick={() => setOpen((v) => !v)}
        className="inline-flex items-center gap-1.5 rounded-full border border-ink-200 bg-white px-2.5 py-1 text-xs font-medium text-ink-500 transition hover:border-ink-900 hover:text-ink-900"
      >
        <InfoGlyph />
        How it works
      </button>

      {open ? (
        <div
          id={panelId}
          role="dialog"
          aria-label={content.title}
          className={`absolute top-full z-50 mt-2 w-80 rounded-2xl border border-ink-200 bg-white p-5 text-left shadow-xl ${
            align === "right" ? "right-0" : "left-0"
          }`}
        >
          <div className="text-xs font-semibold uppercase tracking-widest text-accent">
            {content.title}
          </div>
          {stat ? (
            <div className="mt-2 font-mono text-[11px] text-ink-500">{stat}</div>
          ) : null}
          <p className="mt-2 text-sm leading-relaxed text-ink-700">
            {content.summary}
          </p>

          <dl className="mt-4 space-y-2">
            {content.mechanism.map((m) => (
              <div key={m.label} className="grid grid-cols-[5.5rem_1fr] gap-2">
                <dt className="pt-0.5 text-[10px] font-semibold uppercase tracking-wide text-ink-400">
                  {m.label}
                </dt>
                <dd className="font-mono text-xs leading-relaxed text-ink-900">
                  {m.detail}
                </dd>
              </div>
            ))}
          </dl>

          {content.call ? (
            <pre className="mt-4 overflow-x-auto rounded-lg bg-ink-50 px-3 py-2 font-mono text-[11px] leading-relaxed text-ink-700">
              {content.call}
            </pre>
          ) : null}

          <div className="mt-4 flex flex-wrap gap-x-4 gap-y-1.5 border-t border-ink-200 pt-3">
            {content.docs.map((d) => (
              <a
                key={d.href}
                href={d.href}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 text-xs font-medium text-accent hover:underline"
              >
                {d.label}
                <ArrowUpRight />
              </a>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}

function InfoGlyph() {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className="h-3.5 w-3.5"
      aria-hidden="true"
    >
      <circle cx="12" cy="12" r="10" />
      <path d="M12 16v-4" />
      <path d="M12 8h.01" />
    </svg>
  );
}

function ArrowUpRight() {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className="h-3 w-3"
      aria-hidden="true"
    >
      <path d="M7 17 17 7" />
      <path d="M7 7h10v10" />
    </svg>
  );
}
