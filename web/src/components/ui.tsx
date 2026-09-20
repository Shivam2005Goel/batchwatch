import type { ReactNode } from "react";
import type { Tone, Verdict } from "../types";

/** One place that decides what a colour means, so copy and UI cannot drift. */
export const TONE_STYLE: Record<Tone, { bg: string; border: string; text: string; dot: string }> = {
  red: {
    bg: "bg-red-950/70",
    border: "border-red-800",
    text: "text-red-200",
    dot: "bg-red-500",
  },
  amber: {
    bg: "bg-amber-950/70",
    border: "border-amber-800",
    text: "text-amber-200",
    dot: "bg-amber-500",
  },
  green: {
    bg: "bg-emerald-950/70",
    border: "border-emerald-800",
    text: "text-emerald-200",
    dot: "bg-emerald-500",
  },
  grey: {
    bg: "bg-neutral-900",
    border: "border-neutral-700",
    text: "text-neutral-300",
    dot: "bg-neutral-500",
  },
};

export function toneOf(verdict: Verdict): Tone {
  if (verdict === "FLAGGED") return "red";
  if (verdict === "UNCERTAIN" || verdict === "UNREADABLE") return "amber";
  if (verdict === "NO_MATCH") return "green";
  return "grey";
}

export const SEVERITY_STYLE: Record<string, string> = {
  CRITICAL: "bg-red-500 text-red-950",
  HIGH: "bg-orange-400 text-orange-950",
  MODERATE: "bg-amber-300 text-amber-950",
  LOW: "bg-neutral-400 text-neutral-950",
  UNKNOWN: "bg-neutral-600 text-neutral-100",
  NONE: "bg-emerald-400 text-emerald-950",
};

export function SeverityChip({ severity }: { severity?: string }) {
  if (!severity || severity === "NONE") return null;
  return (
    <span className={`chip ${SEVERITY_STYLE[severity] ?? SEVERITY_STYLE.LOW}`}>{severity}</span>
  );
}

export function Spinner({ label }: { label?: string }) {
  return (
    <div className="flex items-center gap-3 text-sm text-neutral-400">
      <span
        className="h-4 w-4 animate-spin rounded-full border-2 border-neutral-700 border-t-sky-400"
        aria-hidden
      />
      {label ? <span>{label}…</span> : null}
    </div>
  );
}

export function ErrorBox({ message, onRetry, retryLabel }: {
  message: string;
  onRetry?: () => void;
  retryLabel?: string;
}) {
  return (
    <div className="card border-red-900 bg-red-950/40" role="alert">
      <p className="text-sm text-red-200">{message}</p>
      {onRetry ? (
        <button className="btn-ghost mt-3" onClick={onRetry}>
          {retryLabel ?? "Try again"}
        </button>
      ) : null}
    </div>
  );
}

export function Empty({ title, hint, icon }: { title: string; hint?: string; icon?: string }) {
  return (
    <div className="card flex flex-col items-center gap-2 py-12 text-center">
      {icon ? <div className="text-3xl opacity-60">{icon}</div> : null}
      <p className="text-sm font-medium text-neutral-300">{title}</p>
      {hint ? <p className="max-w-xs text-sm text-neutral-500">{hint}</p> : null}
    </div>
  );
}

export function Field({ label, value }: { label: string; value: ReactNode }) {
  if (!value) return null;
  return (
    <div>
      <div className="label">{label}</div>
      <div className="mt-0.5 text-sm text-neutral-100">{value}</div>
    </div>
  );
}

export function Disclaimer({ text }: { text: string }) {
  return (
    <p className="px-1 pb-2 text-[11px] leading-relaxed text-neutral-500">{text}</p>
  );
}

export function SyntheticBanner() {
  return (
    <div className="rounded-xl border border-amber-800/60 bg-amber-950/40 px-3 py-2 text-[11px] text-amber-200">
      Demo corpus: every row here is synthetic sample data, not a real regulator alert.
      Run <span className="batch">scripts/build_seed.py</span> against the CDSCO PDFs for the real thing.
    </div>
  );
}
