import { useEffect, useState } from "react";
import { ApiError, api } from "../api";
import { Empty, ErrorBox, SeverityChip, Spinner, TONE_STYLE, toneOf } from "../components/ui";
import { t } from "../i18n";
import type { Lang, ShelfItem } from "../types";

export function ShelfScreen({ lang, refreshKey }: { lang: Lang; refreshKey: number }) {
  const [items, setItems] = useState<ShelfItem[] | null>(null);
  const [error, setError] = useState("");
  const [removing, setRemoving] = useState("");

  async function load() {
    setError("");
    try {
      const data = await api.shelf();
      setItems(data.items);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
      setItems([]);
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshKey]);

  async function remove(id: string) {
    setRemoving(id);
    try {
      await api.removeFromShelf(id);
      setItems((prev) => (prev ?? []).filter((i) => i.item_id !== id));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setRemoving("");
    }
  }

  if (items === null) {
    return (
      <div className="card">
        <Spinner label={t(lang, "shelf.checking")} />
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <header className="pt-2">
        <h1 className="text-2xl font-bold">{t(lang, "shelf.title")}</h1>
        <p className="mt-1 text-sm text-neutral-500">
          Re-checked against the latest alerts every time you open this.
        </p>
      </header>

      {error ? <ErrorBox message={error} onRetry={() => void load()} /> : null}

      {items.length === 0 && !error ? (
        <Empty title={t(lang, "shelf.empty")} hint={t(lang, "shelf.emptyHint")} icon="▤" />
      ) : null}

      <ul className="space-y-3">
        {items.map((item) => {
          const verdict = item.verdict ?? item.last_verdict;
          const tone = TONE_STYLE[item.tone ?? toneOf(verdict)];
          return (
            <li key={item.item_id} className={`rounded-2xl border ${tone.border} ${tone.bg} p-4`}>
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className={`h-2 w-2 shrink-0 rounded-full ${tone.dot}`} aria-hidden />
                    <h2 className="truncate text-sm font-semibold text-neutral-100">
                      {item.drug_name || "Unnamed medicine"}
                    </h2>
                  </div>
                  <p className="batch mt-1 text-xs text-neutral-400">{item.batch_norm}</p>
                  {item.manufacturer ? (
                    <p className="mt-0.5 truncate text-xs text-neutral-500">{item.manufacturer}</p>
                  ) : null}
                </div>
                <SeverityChip severity={item.severity} />
              </div>

              {verdict === "FLAGGED" && item.match ? (
                <p className="mt-3 rounded-xl bg-neutral-950/50 p-3 text-xs leading-relaxed text-neutral-300">
                  {item.match.failure_reason}
                  <span className="block text-neutral-500">
                    {t(lang, "alerts.flaggedOn", { month: item.match.alert_month })}
                  </span>
                </p>
              ) : null}

              <div className="mt-3 flex items-center justify-between gap-3 text-[11px] text-neutral-500">
                <span>
                  {item.exp_date ? `Expires ${item.exp_date}` : "No expiry recorded"}
                  {item.expired ? " · expired" : ""}
                </span>
                <button
                  className="font-semibold text-neutral-400 underline underline-offset-4 disabled:opacity-40"
                  disabled={removing === item.item_id}
                  onClick={() => void remove(item.item_id)}
                >
                  {t(lang, "shelf.remove")}
                </button>
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
