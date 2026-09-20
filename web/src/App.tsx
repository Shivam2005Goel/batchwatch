import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import { SyntheticBanner } from "./components/ui";
import { storeLang, storedLang, t } from "./i18n";
import { AlertsScreen } from "./screens/AlertsScreen";
import { PharmacyScreen } from "./screens/PharmacyScreen";
import { ScanScreen } from "./screens/ScanScreen";
import { SearchScreen } from "./screens/SearchScreen";
import { ShelfScreen } from "./screens/ShelfScreen";
import type { Lang, Stats } from "./types";

type Tab = "scan" | "shelf" | "alerts" | "pharmacy" | "search";

const TABS: { id: Tab; icon: string }[] = [
  { id: "scan", icon: "▣" },
  { id: "shelf", icon: "▤" },
  { id: "alerts", icon: "!" },
  { id: "pharmacy", icon: "⊞" },
  { id: "search", icon: "⌕" },
];

export default function App() {
  const [tab, setTab] = useState<Tab>("scan");
  const [lang, setLang] = useState<Lang>(storedLang);
  const [stats, setStats] = useState<Stats | null>(null);
  const [unread, setUnread] = useState(0);
  const [refreshKey, setRefreshKey] = useState(0);

  const changeLang = useCallback((next: Lang) => {
    setLang(next);
    storeLang(next);
  }, []);

  useEffect(() => {
    void api.stats().then(setStats).catch(() => setStats(null));
  }, []);

  // Poll the alert count so the badge appears the moment an ingest run fans
  // out - which is exactly the beat the demo turns on.
  useEffect(() => {
    let cancelled = false;
    async function poll() {
      try {
        const data = await api.alerts(false);
        if (!cancelled) setUnread(data.unread);
      } catch {
        /* an unreachable API is already reported by whichever screen is open */
      }
    }
    void poll();
    const timer = window.setInterval(poll, 10_000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [refreshKey, tab]);

  const bump = useCallback(() => setRefreshKey((k) => k + 1), []);

  return (
    <div className="mx-auto flex min-h-full w-full max-w-lg flex-col">
      <header className="safe-top sticky top-0 z-10 border-b border-neutral-900 bg-neutral-950/90 px-4 py-3 backdrop-blur">
        <div className="flex items-baseline justify-between">
          <span className="text-sm font-bold tracking-tight">
            Batch<span className="text-sky-400">Watch</span>
          </span>
          {stats ? (
            <span className="text-[10px] text-neutral-600">
              {stats.rows.toLocaleString()} flagged batches · {stats.latest_alert_month}
            </span>
          ) : null}
        </div>
      </header>

      <main className="flex-1 space-y-4 px-4 pb-28 pt-2">
        {stats?.corpus_is_synthetic ? <SyntheticBanner /> : null}

        {tab === "scan" ? (
          <ScanScreen lang={lang} onLangChange={changeLang} onSaved={bump} />
        ) : null}
        {tab === "shelf" ? <ShelfScreen lang={lang} refreshKey={refreshKey} /> : null}
        {tab === "alerts" ? <AlertsScreen lang={lang} refreshKey={refreshKey} /> : null}
        {tab === "pharmacy" ? <PharmacyScreen lang={lang} /> : null}
        {tab === "search" ? <SearchScreen lang={lang} stats={stats} /> : null}
      </main>

      <nav className="safe-bottom fixed inset-x-0 bottom-0 z-10 mx-auto w-full max-w-lg border-t border-neutral-900 bg-neutral-950/95 backdrop-blur">
        <ul className="grid grid-cols-5">
          {TABS.map((item) => {
            const active = tab === item.id;
            return (
              <li key={item.id}>
                <button
                  className={`flex w-full flex-col items-center gap-0.5 py-2.5 text-[10px] font-medium transition ${
                    active ? "text-sky-400" : "text-neutral-500"
                  }`}
                  onClick={() => setTab(item.id)}
                  aria-current={active ? "page" : undefined}
                >
                  <span className="relative text-lg leading-none" aria-hidden>
                    {item.icon}
                    {item.id === "alerts" && unread > 0 ? (
                      <span className="absolute -right-2 -top-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-red-500 px-1 text-[9px] font-bold text-white">
                        {unread > 9 ? "9+" : unread}
                      </span>
                    ) : null}
                  </span>
                  {t(lang, `nav.${item.id}`)}
                </button>
              </li>
            );
          })}
        </ul>
      </nav>
    </div>
  );
}
