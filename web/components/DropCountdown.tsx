"use client";

import { useEffect, useState } from "react";
import { nextDropAtMs } from "@/lib/drops";

function pad(n: number): string {
  return String(n).padStart(2, "0");
}

// Ticks down to the next nightly reindex. Renders a placeholder until
// mounted so the server and first client render agree.
export function DropCountdown({ className }: { className?: string }) {
  const [now, setNow] = useState<number | null>(null);

  useEffect(() => {
    setNow(Date.now());
    const t = setInterval(() => setNow(Date.now()), 1_000);
    return () => clearInterval(t);
  }, []);

  if (now === null) {
    return (
      <span className={className} suppressHydrationWarning>
        --:--:--
      </span>
    );
  }
  const ms = Math.max(0, nextDropAtMs(now) - now);
  const h = Math.floor(ms / 3_600_000);
  const m = Math.floor((ms % 3_600_000) / 60_000);
  const s = Math.floor((ms % 60_000) / 1_000);
  return (
    <span className={className} suppressHydrationWarning>
      {pad(h)}:{pad(m)}:{pad(s)}
    </span>
  );
}
