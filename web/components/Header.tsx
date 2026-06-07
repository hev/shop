import Link from "next/link";
import { SearchBar } from "./SearchBar";
import { Suspense } from "react";

export function Header() {
  return (
    <header className="sticky top-0 z-40 border-b border-ink-200 bg-ink-50/85 backdrop-blur">
      <div className="bg-ink-900 text-ink-100">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-4 py-1.5 text-xs">
          <span>Free cosine similarity metric with every search</span>
          <span className="hidden sm:inline">no keywords were harmed in the making of these results</span>
        </div>
      </div>

      <div className="mx-auto flex max-w-7xl flex-col gap-3 px-4 py-4 sm:flex-row sm:items-center sm:gap-6">
        <Link href="/" className="flex shrink-0 items-baseline gap-1">
          <span className="font-display text-2xl tracking-tight">hev</span>
          <span className="font-display text-2xl italic text-accent">·</span>
          <span className="font-display text-2xl tracking-tight">shop</span>
        </Link>

        <div className="flex-1">
          <Suspense fallback={<div className="h-10 w-full rounded-full border border-ink-200 bg-white" />}>
            <SearchBar />
          </Suspense>
        </div>

        <nav className="flex shrink-0 items-center gap-5 text-sm text-ink-700">
          <Link href="/" className="hover:text-ink-900">Shop</Link>
          <Link href="/drops" className="relative hover:text-ink-900">
            Drops
            <span
              aria-hidden
              className="absolute -right-2 top-0 h-1.5 w-1.5 rounded-full bg-accent"
            />
          </Link>
          <Link href="/search?q=" className="hover:text-ink-900">All</Link>
          <button
            aria-label="Cart"
            className="relative rounded-full border border-ink-200 bg-white p-2 transition hover:border-ink-900"
          >
            <svg
              xmlns="http://www.w3.org/2000/svg"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              className="h-4 w-4"
            >
              <circle cx="9" cy="21" r="1" />
              <circle cx="20" cy="21" r="1" />
              <path d="M1 1h4l2.7 13.4a2 2 0 0 0 2 1.6h9.7a2 2 0 0 0 2-1.6L23 6H6" />
            </svg>
          </button>
        </nav>
      </div>
    </header>
  );
}
