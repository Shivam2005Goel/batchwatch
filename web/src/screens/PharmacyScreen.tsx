import { useMemo, useState } from "react";
import { ApiError, api } from "../api";
import { Disclaimer, ErrorBox, SeverityChip, Spinner, TONE_STYLE, toneOf } from "../components/ui";
import { t } from "../i18n";
import type { Lang, PharmacyJob, Verdict } from "../types";

const SAMPLE = `product,batch,manufacturer,expiry
Paracetamol Tablets IP 650mg,KP4021H,Vireon Laboratories Ltd,2028-02
Azithromycin Tablets IP 500mg,AZ9931K,Trisara Labs Ltd,2027-10
Amlodipine Tablets IP 5mg,T2451C,Kavisha Remedies Ltd,2027-12`;

const GROUPS: { key: Verdict; labelKey: string }[] = [
  { key: "FLAGGED", labelKey: "pharmacy.flagged" },
  { key: "UNCERTAIN", labelKey: "pharmacy.uncertain" },
  { key: "NO_MATCH", labelKey: "pharmacy.clear" },
  { key: "SKIPPED", labelKey: "pharmacy.skipped" },
];

export function PharmacyScreen({ lang }: { lang: Lang }) {
  const [csv, setCsv] = useState("");
  const [job, setJob] = useState<PharmacyJob | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const lineCount = useMemo(
    () => csv.split("\n").filter((l) => l.trim()).length,
    [csv],
  );

  async function check() {
    setBusy(true);
    setError("");
    setJob(null);
    try {
      setJob(await api.pharmacyCheck(csv));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-4">
      <header className="pt-2">
        <h1 className="text-2xl font-bold">{t(lang, "pharmacy.title")}</h1>
        <p className="mt-1 text-sm text-neutral-500">
          One chemist checking their shelf protects everyone who would have bought from it.
        </p>
      </header>

      <div className="card">
        <p className="text-xs text-neutral-500">{t(lang, "pharmacy.hint")}</p>
        <textarea
          className="field mt-3 h-44 resize-none font-mono text-xs leading-relaxed"
          placeholder={SAMPLE}
          value={csv}
          onChange={(e) => setCsv(e.target.value)}
        />
        <div className="mt-3 flex gap-2">
          <button
            className="btn-primary flex-1"
            disabled={busy || lineCount === 0}
            onClick={() => void check()}
          >
            {t(lang, "pharmacy.check", { n: lineCount })}
          </button>
          <button className="btn-ghost" onClick={() => setCsv(SAMPLE)} disabled={busy}>
            Sample
          </button>
        </div>
      </div>

      {busy ? (
        <div className="card">
          <Spinner label={t(lang, "pharmacy.checking")} />
        </div>
      ) : null}

      {error ? <ErrorBox message={error} /> : null}

      {job ? (
        <>
          <div className="grid grid-cols-4 gap-2">
            {GROUPS.map((g) => {
              const tone = TONE_STYLE[toneOf(g.key)];
              const n = job.counts[g.key] ?? 0;
              return (
                <div
                  key={g.key}
                  className={`rounded-xl border ${tone.border} ${tone.bg} p-2 text-center`}
                >
                  <div className="text-xl font-bold text-neutral-50">{n}</div>
                  <div className="text-[10px] leading-tight text-neutral-400">
                    {t(lang, g.labelKey)}
                  </div>
                </div>
              );
            })}
          </div>

          <ul className="space-y-2">
            {job.results.map((row) => {
              const tone = TONE_STYLE[row.tone ?? toneOf(row.verdict)];
              return (
                <li
                  key={row.line}
                  className={`rounded-xl border ${tone.border} ${tone.bg} px-3 py-2.5`}
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium text-neutral-100">
                        {row.input.drug_name || `${t(lang, "pharmacy.line")} ${row.line}`}
                      </p>
                      <p className="batch text-[11px] text-neutral-400">
                        {row.input.batch || "no batch"}
                      </p>
                    </div>
                    <SeverityChip severity={row.severity} />
                  </div>
                  {row.verdict !== "NO_MATCH" ? (
                    <p className="mt-1.5 text-[11px] leading-relaxed text-neutral-400">
                      {row.match?.failure_reason || row.reason}
                    </p>
                  ) : null}
                </li>
              );
            })}
          </ul>

          <Disclaimer text={job.disclaimer} />
        </>
      ) : null}
    </div>
  );
}
