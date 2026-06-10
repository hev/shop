"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useId, useRef, useState } from "react";
import {
  getRecentSearchesLocal,
  RECENT_SEARCHES_EVENT,
} from "@/lib/recent-searches-local";
import { searchHref, truncateQuery } from "@/lib/search-ui";

export function SearchBar({ size = "md" }: { size?: "md" | "lg" }) {
  const router = useRouter();
  const params = useSearchParams();
  const [q, setQ] = useState(params.get("q") ?? "");

  // Personal recent-search suggestions: browser-local, private, and refreshed
  // when /search records a newly submitted query.
  const [recent, setRecent] = useState<string[]>([]);
  const [open, setOpen] = useState(false);
  const [highlight, setHighlight] = useState(-1);
  const wrapRef = useRef<HTMLDivElement>(null);
  const listboxId = useId();

  useEffect(() => {
    setQ(params.get("q") ?? "");
  }, [params]);

  useEffect(() => {
    function refresh() {
      setRecent(getRecentSearchesLocal(8));
    }
    refresh();
    window.addEventListener(RECENT_SEARCHES_EVENT, refresh);
    return () => window.removeEventListener(RECENT_SEARCHES_EVENT, refresh);
  }, []);

  // Suggestions, not autocomplete: the dropdown only shows while the field is
  // empty (0.1 doesn't filter the list against the typed prefix), and only when
  // there's something to suggest.
  const showing = open && q.trim() === "" && recent.length > 0;

  // Reset the keyboard highlight whenever the dropdown shows/hides or the query
  // changes underneath it.
  useEffect(() => {
    setHighlight(-1);
  }, [showing, q]);

  // Outside-click closes the dropdown (Esc is handled on the input). Mirrors the
  // FeatureExplainer popover pattern; the suggestion buttons preventDefault on
  // mousedown so selecting one keeps focus and doesn't trip this.
  useEffect(() => {
    if (!showing) return;
    function onDown(e: MouseEvent) {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [showing]);

  function go(query: string) {
    const trimmed = query.trim();
    setOpen(false);
    router.push(trimmed ? searchHref(trimmed) : "/search");
  }

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    go(q);
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Escape") {
      setOpen(false);
      return;
    }
    if (!showing) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setHighlight((h) => Math.min(h + 1, recent.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setHighlight((h) => Math.max(h - 1, -1));
    } else if (e.key === "Enter" && highlight >= 0) {
      // Run the highlighted suggestion; otherwise fall through to form submit
      // with whatever's typed.
      e.preventDefault();
      go(recent[highlight]);
    }
  };

  const padding = size === "lg" ? "py-4 px-6 text-lg" : "py-2.5 px-4 text-sm";

  return (
    <form onSubmit={onSubmit} className="w-full">
      <div ref={wrapRef} className="relative w-full">
        <input
          type="search"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onFocus={() => {
            setOpen(true);
            setRecent(getRecentSearchesLocal(8));
          }}
          onKeyDown={onKeyDown}
          role="combobox"
          aria-expanded={showing}
          aria-controls={showing ? listboxId : undefined}
          aria-autocomplete="list"
          aria-activedescendant={
            showing && highlight >= 0 ? `${listboxId}-${highlight}` : undefined
          }
          placeholder="Describe a vibe — ‘cozy reading corner’, ‘something brass and warm’, ‘brutalist but soft’…"
          className={`w-full rounded-full border border-ink-200 bg-white ${padding} pr-12 outline-none transition focus:border-ink-900 focus:ring-2 focus:ring-ink-900/10`}
        />
        <button
          type="submit"
          aria-label="Search"
          className="absolute right-1.5 top-1/2 -translate-y-1/2 rounded-full bg-ink-900 p-2 text-white transition hover:bg-ink-700"
        >
          <svg
            xmlns="http://www.w3.org/2000/svg"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            className={size === "lg" ? "h-5 w-5" : "h-4 w-4"}
          >
            <circle cx="11" cy="11" r="7" />
            <path d="m20 20-3.5-3.5" />
          </svg>
        </button>

        {showing ? (
          <div
            id={listboxId}
            role="listbox"
            aria-label="Recent searches"
            className="absolute left-0 right-0 top-full z-50 mt-2 rounded-2xl border border-ink-200 bg-white p-2 text-left shadow-xl"
          >
            <div className="px-2 pb-1 pt-0.5 text-[10px] font-semibold uppercase tracking-widest text-ink-400">
              Recent searches
            </div>
            {recent.map((query, i) => (
              <button
                type="button"
                key={query}
                id={`${listboxId}-${i}`}
                role="option"
                aria-selected={i === highlight}
                title={query}
                onMouseEnter={() => setHighlight(i)}
                // Keep focus on the input so the click lands before any blur.
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => go(query)}
                className={`flex w-full items-center gap-2 rounded-lg px-3 py-1.5 text-left text-sm transition ${
                  i === highlight
                    ? "bg-ink-50 text-ink-900"
                    : "text-ink-700 hover:bg-ink-50"
                }`}
              >
                <SuggestGlyph />
                <span className="truncate">{truncateQuery(query)}</span>
              </button>
            ))}
          </div>
        ) : null}
      </div>
    </form>
  );
}

function SuggestGlyph() {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className="h-3.5 w-3.5 shrink-0 text-ink-400"
      aria-hidden="true"
    >
      <circle cx="11" cy="11" r="7" />
      <path d="m20 20-3.5-3.5" />
    </svg>
  );
}
