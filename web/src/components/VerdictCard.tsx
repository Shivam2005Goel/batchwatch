import { useState } from "react";
import { LANGS, t } from "../i18n";
import type { Lang, ScanResult } from "../types";
import { Disclaimer, Field, SeverityChip, TONE_STYLE, toneOf } from "./ui";

/**
 * The screen the whole app is judged on.
 *
 * One colour, one sentence, one instruction. Everything else - the score, the
 * candidates, what the model actually read - is available but folded away,
 * because a person holding a medicine strip needs the answer first.
 */
export function VerdictCard({
  result,
  lang,
  onLangChange,
  onSave,
  saveState,
  onReset,
  resetLabel,
}: {
  result: ScanResult;
  lang: Lang;
  onLangChange: (lang: Lang) => void;
  onSave?: () => void;
  saveState?: "idle" | "saving" | "saved";
  onReset?: () => void;
  resetLabel?: string;
}) {
  const [showDetail, setShowDetail] = useState(false);
  const tone = TONE_STYLE[result.tone ?? toneOf(result.verdict)];
  const row = result.match;
  const advice = result.advice?.[lang] ?? result.advice?.en ?? "";

  return (
    <div className="space-y-4">
      <section className={`rounded-3xl border ${tone.border} ${tone.bg} p-5`}>
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-center gap-2">
            <span className={`h-2.5 w-2.5 rounded-full ${tone.dot}`} aria-hidden />
            <span className={`text-[11px] font-bold uppercase tracking-widest ${tone.text}`}>
              {result.verdict.replace("_", " ")}
            </span>
          </div>
          <SeverityChip severity={result.severity} />
        </div>

        <h2 className="mt-3 text-2xl font-bold leading-tight text-neutral-50">
          {result.headline}
        </h2>

        {result.extracted?.batch ? (
          <p className="batch mt-3 text-lg text-neutral-200">{result.extracted.batch}</p>
        ) : null}

        {advice ? (
          <div className="mt-4 rounded-2xl bg-neutral-950/50 p-4">
            <div className="label">{t(lang, "verdict.whatToDo")}</div>
            <p className="mt-1 text-[15px] leading-relaxed text-neutral-100">{advice}</p>
          </div>
        ) : null}

        {result.reason ? (
          <p className="mt-3 text-sm leading-relaxed text-neutral-400">{result.reason}</p>
        ) : null}

        {result.expired ? (
          <p className="mt-3 text-sm font-medium text-amber-300">{t(lang, "verdict.expired")}</p>
        ) : null}

        {result.adjudicated ? (
          <p className="mt-3 text-[11px] text-neutral-500">{t(lang, "verdict.adjudicated")}</p>
        ) : null}

        <div className="mt-4 flex flex-wrap gap-1.5">
          {LANGS.map((l) => (
            <button
              key={l.code}
              onClick={() => onLangChange(l.code)}
              className={`chip border ${
                lang === l.code
                  ? "border-neutral-300 bg-neutral-100 text-neutral-900"
                  : "border-neutral-700 text-neutral-400"
              }`}
            >
              {l.label}
            </button>
          ))}
        </div>
      </section>

      {row ? (
        <section className="card space-y-3">
          <Field label={t(lang, "verdict.product")} value={row.drug_name} />
          <Field label={t(lang, "verdict.manufacturer")} value={row.manufacturer_raw} />
          <div className="grid grid-cols-2 gap-3">
            <Field
              label={t(lang, "verdict.batch")}
              value={<span className="batch">{row.batch_norm}</span>}
            />
            <Field label={t(lang, "verdict.expiry")} value={row.exp_date} />
          </div>
          <Field label={t(lang, "verdict.reason")} value={row.failure_reason} />
          <div className="grid grid-cols-2 gap-3">
            <Field label={t(lang, "verdict.published")} value={row.alert_month} />
            <Field label="Tested at" value={row.lab} />
          </div>
          {row.source_url ? (
            <a
              className="inline-block text-sm font-medium text-sky-400 underline underline-offset-4"
              href={row.source_url}
              target="_blank"
              rel="noreferrer noopener"
            >
              {t(lang, "verdict.source")} →
            </a>
          ) : null}
        </section>
      ) : null}

      <div className="flex gap-2">
        {onSave ? (
          <button
            className="btn-primary flex-1"
            onClick={onSave}
            disabled={saveState !== "idle"}
          >
            {saveState === "saved"
              ? t(lang, "scan.saved")
              : saveState === "saving"
                ? `${t(lang, "scan.saving")}…`
                : t(lang, "scan.save")}
          </button>
        ) : null}
        {onReset ? (
          <button className="btn-ghost flex-1" onClick={onReset}>
            {resetLabel ?? t(lang, "scan.again")}
          </button>
        ) : null}
      </div>

      <button
        className="w-full text-left text-[11px] font-semibold uppercase tracking-wider text-neutral-500"
        onClick={() => setShowDetail((v) => !v)}
      >
        {showDetail ? "− " : "+ "}
        How this was decided
      </button>

      {showDetail ? (
        <section className="card space-y-3 text-xs text-neutral-400">
          {result.extracted ? (
            <div>
              <div className="label">{t(lang, "verdict.whatWeRead")}</div>
              <dl className="mt-1 space-y-0.5">
                {(
                  [
                    ["batch", result.extracted.batch],
                    ["product", result.extracted.drug_name],
                    ["manufacturer", result.extracted.manufacturer],
                    ["expiry", result.extracted.exp_date],
                  ] as const
                ).map(([k, v]) => (
                  <div key={k} className="flex justify-between gap-3">
                    <dt className="text-neutral-600">{k}</dt>
                    <dd className="text-right text-neutral-300">{v || "—"}</dd>
                  </div>
                ))}
                <div className="flex justify-between gap-3">
                  <dt className="text-neutral-600">read by</dt>
                  <dd className="text-right text-neutral-300">{result.extracted.source}</dd>
                </div>
              </dl>
            </div>
          ) : null}

          {typeof result.score === "number" ? (
            <div>
              <div className="label">{t(lang, "verdict.confidence")}</div>
              <div className="mt-1 flex items-center gap-2">
                <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-neutral-800">
                  <div
                    className={`h-full ${tone.dot}`}
                    style={{ width: `${Math.round(result.score * 100)}%` }}
                  />
                </div>
                <span className="batch text-neutral-300">
                  {(result.score * 100).toFixed(1)}%
                </span>
              </div>
            </div>
          ) : null}

          {result.candidates?.length ? (
            <div>
              <div className="label">Closest flagged batches</div>
              <ul className="mt-1 space-y-1">
                {result.candidates.map((c, i) => (
                  <li key={i} className="flex justify-between gap-3">
                    <span className="batch text-neutral-300">{c.batch}</span>
                    <span className="text-neutral-600">
                      {c.alert_month} · {(c.score * 100).toFixed(0)}%
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </section>
      ) : null}

      <Disclaimer text={result.disclaimer} />
    </div>
  );
}
