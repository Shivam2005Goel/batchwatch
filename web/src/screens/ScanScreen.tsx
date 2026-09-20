import { useRef, useState } from "react";
import { ApiError, api, downscale } from "../api";
import { VerdictCard } from "../components/VerdictCard";
import { ErrorBox, Spinner } from "../components/ui";
import { t } from "../i18n";
import type { Lang, ScanResult } from "../types";

type SaveState = "idle" | "saving" | "saved";

export function ScanScreen({
  lang,
  onLangChange,
  onSaved,
}: {
  lang: Lang;
  onLangChange: (l: Lang) => void;
  onSaved: () => void;
}) {
  const [result, setResult] = useState<ScanResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [text, setText] = useState("");
  const [resize, setResize] = useState("");
  const [saveState, setSaveState] = useState<SaveState>("idle");
  const fileRef = useRef<HTMLInputElement>(null);

  async function run(fn: () => Promise<ScanResult>) {
    setBusy(true);
    setError("");
    setResult(null);
    setSaveState("idle");
    try {
      setResult(await fn());
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function onFile(file: File) {
    setResize("");
    await run(async () => {
      const shrunk = await downscale(file);
      setResize(t(lang, "scan.resized", { from: shrunk.originalKB, to: shrunk.sentKB }));
      return api.scanImage(shrunk.data, shrunk.mediaType, text.trim());
    });
  }

  async function save() {
    if (!result?.extracted) return;
    setSaveState("saving");
    try {
      await api.addToShelf({
        drug_name: result.extracted.drug_name || result.match?.drug_name || "Unnamed medicine",
        batch: result.extracted.batch,
        manufacturer: result.extracted.manufacturer,
        mfg_date: result.extracted.mfg_date,
        exp_date: result.extracted.exp_date,
        verdict: result.verdict,
      });
      setSaveState("saved");
      onSaved();
    } catch (err) {
      setSaveState("idle");
      setError(err instanceof ApiError ? err.message : String(err));
    }
  }

  function reset() {
    setResult(null);
    setError("");
    setResize("");
    setText("");
    setSaveState("idle");
    if (fileRef.current) fileRef.current.value = "";
  }

  if (result) {
    return (
      <VerdictCard
        result={result}
        lang={lang}
        onLangChange={onLangChange}
        onSave={result.extracted?.batch ? save : undefined}
        saveState={saveState}
        onReset={reset}
      />
    );
  }

  return (
    <div className="space-y-5">
      <div className="pt-2 text-center">
        <h1 className="text-2xl font-bold">{t(lang, "app.tagline")}</h1>
        <p className="mt-1 text-sm text-neutral-500">{t(lang, "scan.hint")}</p>
      </div>

      <label
        className="flex cursor-pointer flex-col items-center justify-center gap-3
                   rounded-3xl border-2 border-dashed border-neutral-700 bg-neutral-900/40
                   px-6 py-14 text-center transition active:scale-[0.99] hover:border-sky-600"
      >
        {/* A plain file input with `capture` opens the camera on every phone and
            needs no permission dance, unlike getUserMedia. */}
        <input
          ref={fileRef}
          type="file"
          accept="image/*"
          capture="environment"
          className="sr-only"
          disabled={busy}
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) void onFile(file);
          }}
        />
        <span className="text-4xl" aria-hidden>
          ▣
        </span>
        <span className="text-base font-semibold text-neutral-100">{t(lang, "scan.cta")}</span>
        <span className="text-xs text-neutral-500">JPG or PNG · resized on your device</span>
      </label>

      {busy ? (
        <div className="card">
          <Spinner label={t(lang, "scan.reading")} />
        </div>
      ) : null}

      {resize ? <p className="text-center text-[11px] text-neutral-600">{resize}</p> : null}

      {error ? <ErrorBox message={error} /> : null}

      <details className="card" open={!!text}>
        <summary className="cursor-pointer text-sm font-semibold text-neutral-300">
          {t(lang, "scan.typeInstead")}
        </summary>
        <textarea
          className="field mt-3 h-36 resize-none font-mono text-xs leading-relaxed"
          placeholder={t(lang, "scan.typePlaceholder")}
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
        <button
          className="btn-primary mt-3 w-full"
          disabled={busy || text.trim().length < 3}
          onClick={() => void run(() => api.scanText(text.trim()))}
        >
          {t(lang, "scan.check")}
        </button>
        <p className="mt-2 text-[11px] text-neutral-600">
          Works with no model in the loop, and it is the fallback when the camera cannot
          read embossed foil.
        </p>
      </details>
    </div>
  );
}
