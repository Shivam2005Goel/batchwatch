import { useEffect, useState } from "react";
import { ApiError, api } from "../api";
import { Empty, ErrorBox, SeverityChip, Spinner } from "../components/ui";
import { t } from "../i18n";
import type { Alert, Lang } from "../types";

/**
 * The screen the project exists for.
 *
 * Everything here arrived without the user doing anything: they saved a
 * medicine weeks ago, the regulator published a list today, and the batch
 * matched.
 */
export function AlertsScreen({ lang, refreshKey }: { lang: Lang; refreshKey: number }) {
  const [alerts, setAlerts] = useState<Alert[] | null>(null);
  const [error, setError] = useState("");

  async function load() {
    setError("");
    try {
      const data = await api.alerts(true);
      setAlerts(data.alerts);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
      setAlerts([]);
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshKey]);

  if (alerts === null) {
    return (
      <div className="card">
        <Spinner label={t(lang, "common.loading")} />
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <header className="pt-2">
        <h1 className="text-2xl font-bold">{t(lang, "alerts.title")}</h1>
        <p className="mt-1 text-sm text-neutral-500">
          Recalls that reached you after you already bought the medicine.
        </p>
      </header>

      {error ? <ErrorBox message={error} onRetry={() => void load()} /> : null}

      {alerts.length === 0 && !error ? (
        <Empty title={t(lang, "alerts.empty")} hint={t(lang, "alerts.emptyHint")} icon="✓" />
      ) : null}

      <ul className="space-y-3">
        {alerts.map((alert) => (
          <li key={alert.alert_id} className="rounded-2xl border border-red-900 bg-red-950/50 p-4">
            <div className="flex items-start justify-between gap-3">
              <h2 className="text-sm font-semibold text-neutral-50">{alert.drug_name}</h2>
              <SeverityChip severity={alert.severity} />
            </div>
            <p className="batch mt-1 text-xs text-red-200">{alert.batch_norm}</p>
            <p className="mt-3 text-sm leading-relaxed text-neutral-200">{alert.failure_reason}</p>
            <p className="mt-2 text-[11px] text-neutral-400">
              {alert.manufacturer}
              {alert.alert_month ? ` · ${t(lang, "alerts.flaggedOn", { month: alert.alert_month })}` : ""}
            </p>
            {alert.source_url ? (
              <a
                className="mt-2 inline-block text-xs font-medium text-sky-400 underline underline-offset-4"
                href={alert.source_url}
                target="_blank"
                rel="noreferrer noopener"
              >
                {t(lang, "verdict.source")} →
              </a>
            ) : null}
          </li>
        ))}
      </ul>
    </div>
  );
}
