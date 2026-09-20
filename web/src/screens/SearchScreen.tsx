import { useState } from "react";
import { ApiError, api } from "../api";
import { Empty, ErrorBox, SeverityChip, Spinner } from "../components/ui";
import { t } from "../i18n";
import type { Lang, NsqRow, Stats } from "../types";

export function SearchScreen({ lang, stats }: { lang: Lang; stats: Stats | null }) {
  const [q, setQ] = useState("");
  const [rows, setRows] = useState<NsqRow[] | null>(null);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function run(e?: React.FormEvent) {
    e?.preventDefault();
    if (q.trim().length < 3) return;
    setBusy(true);
    setError("");
    try {
      const data = await api.search(q.trim());
      setRows(data.results);
      setNote(data.note);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
      setRows([]);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-4">
      <header className="pt-2">
        <h1 className="text-2xl font-bold">{t(lang, "search.title")}</h1>
        <p className="mt-1 text-sm text-neutral-500">{t(lang, "search.hint")}</p>
      </header>

      <form onSubmit={run} className="flex gap-2">
        <input
          className="field flex-1"
          placeholder={t(lang, "search.placeholder")}
          value={q}
          onChange={(e) => setQ(e.target.value)}
          autoCapitalize="characters"
          autoCorrect="off"
          spellCheck={false}
        />
        <button className="btn-primary" disabled={busy || q.trim().length < 3}>
          Go
        </button>
      </form>

      {stats ? (
        <p className="text-[11px] text-neutral-600">
          {t(lang, "common.corpus", { rows: stats.rows, months: stats.alert_months })}
          {stats.latest_alert_month ? ` · latest ${stats.latest_alert_month}` : ""}
        </p>
      ) : null}

      {busy ? (
        <div className="card">
          <Spinner label={t(lang, "common.loading")} />
        </div>
      ) : null}

      {error ? <ErrorBox message={error} onRetry={() => void run()} /> : null}

      {rows !== null && rows.length === 0 && !busy && !error ? (
        <Empty title={t(lang, "search.none")} hint="That is not a guarantee it is safe." />
      ) : null}

      {rows && rows.length > 0 ? (
        <>
          <p className="text-[11px] text-neutral-500">
            {t(lang, "search.results", { n: rows.length })}
          </p>
          <ul className="space-y-2">
            {rows.map((row, i) => (
              <li key={`${row.batch_norm}-${i}`} className="card">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="truncate text-sm font-semibold text-neutral-100">
                      {row.drug_name}
                    </p>
                    <p className="batch mt-0.5 text-xs text-neutral-400">{row.batch_norm}</p>
                  </div>
                  <SeverityChip severity={row.severity} />
                </div>
                <p className="mt-2 text-xs leading-relaxed text-neutral-400">
                  {row.failure_reason}
                </p>
                <p className="mt-1.5 text-[11px] text-neutral-600">
                  {row.manufacturer_raw}
                  {row.alert_month ? ` · ${row.alert_month}` : ""}
                  {row.exp_date ? ` · exp ${row.exp_date}` : ""}
                </p>
              </li>
            ))}
          </ul>
          {note ? <p className="px-1 text-[11px] leading-relaxed text-neutral-500">{note}</p> : null}
        </>
      ) : null}
    </div>
  );
}
