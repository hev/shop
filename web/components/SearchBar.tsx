"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

export function SearchBar({ size = "md" }: { size?: "md" | "lg" }) {
  const router = useRouter();
  const params = useSearchParams();
  const [q, setQ] = useState(params.get("q") ?? "");

  useEffect(() => {
    setQ(params.get("q") ?? "");
  }, [params]);

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = q.trim();
    router.push(trimmed ? `/search?q=${encodeURIComponent(trimmed)}` : "/search");
  };

  const padding = size === "lg" ? "py-4 px-6 text-lg" : "py-2.5 px-4 text-sm";

  return (
    <form onSubmit={onSubmit} className="w-full">
      <div className="relative w-full">
        <input
          type="search"
          value={q}
          onChange={(e) => setQ(e.target.value)}
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
      </div>
    </form>
  );
}
