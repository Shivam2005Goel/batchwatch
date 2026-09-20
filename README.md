# BatchWatch

**A recall that travels backwards in time — to the person who already bought the strip.**

Every month India's drug regulator (CDSCO) publishes a list of medicine batches that failed
quality testing. The list comes out weeks after the medicine is already in someone's home, and
India has no mandatory mechanism that carries a recall the last mile to the household. The
medicine gets consumed before it leaves circulation.

BatchWatch closes that gap without needing anyone's permission:

1. **Scan a strip** — photograph the foil, get a verdict in seconds.
2. **My shelf** — scanned medicines are remembered. When next month's CDSCO list contains a
   batch already sitting on someone's shelf, they are told. *This is the point of the project.*
3. **Pharmacy mode** — a chemist pastes a stock list and sees which shelf items are flagged.

Surfaces 1 and 3 are lookups. Surface 2 is the thing nobody has built.

---

## Status

Everything below runs today, offline, with no AWS account:

| Area | State |
|---|---|
| Matching engine | Working, 139 tests green |
| Scan (typed label text) | Working end to end |
| Scan (photo → Bedrock vision) | Code complete; **not executed against live Bedrock** — see *Known limitations* |
| Shelf + retroactive alerts | Working end to end, covered by tests |
| Pharmacy bulk check | Working end to end |
| Public search + stats | Working |
| Ingest pipeline (extract → normalise → fan-out) | Working; the CDSCO *fetch* scraper is untested against the live site |
| Web app | Builds and runs; six screens |
| SAM template + state machine | Structurally validated; **not deploy-tested** — no SAM CLI in the build environment |
| Corpus | **Synthetic sample data** — see *About the data* |

---

## Quick start

Needs Python 3.11+ and Node 18+. No AWS account, no credentials, no Docker.

```bash
pip install -r requirements-dev.txt

python scripts/make_sample_seed.py                      # generate the sample corpus
python scripts/load_seed.py --holdback-month 2026-08    # load it, keep one month back

cd web && npm install && npm run build && cd ..
python scripts/serve_local.py
```

Open <http://127.0.0.1:8000>.

For frontend work, run the API and Vite side by side instead — Vite proxies to the API:

```bash
python scripts/serve_local.py        # terminal 1
cd web && npm run dev                # terminal 2, http://127.0.0.1:5173
```

`scripts/serve_local.py` is **not a mock**. It builds real API Gateway HTTP API v2 events and
calls the real Lambda handlers, which talk to the real repository layer. The only thing that
changes when you deploy is which `Store` driver `get_store()` picks.

---

## The demo

This is the sequence worth recording. It takes about ninety seconds.

```bash
python scripts/load_seed.py --holdback-month 2026-08   # 2026-08 is NOT in the database
python scripts/serve_local.py
```

1. **Scan a medicine from the held-back month.** It comes back green — that batch genuinely is
   not in the corpus yet.
2. **Save it to your shelf.**
3. **Publish the month the regulator was sitting on:**

   ```bash
   curl -X POST http://127.0.0.1:8000/admin/ingest \
     -H 'content-type: application/json' \
     -H 'x-admin-key: local-dev-key' \
     -d "{\"rows\": $(python -c "import json,pathlib;print(json.dumps([json.loads(l) for l in pathlib.Path('data/nsq_holdback.jsonl').read_text(encoding='utf-8').splitlines() if l.strip()]))")}"
   ```

4. **The alert is already waiting.** The badge appears on the Alerts tab within ten seconds;
   the shelf item has turned red. Nobody scanned anything again.

That step 3→4 transition is the entire argument of the project. It is covered by
`test_a_recall_published_later_reaches_the_shelf` in `tests/test_api.py`.

---

## Architecture

Two loops that meet at the fan-out matcher.

```
READ LOOP (seconds)
  PWA ──► API Gateway HTTP API ──► Lambda ──► Bedrock (vision)
                                      │
                                      └──► matcher ──► DynamoDB

INGEST LOOP (monthly, unattended)
  EventBridge Scheduler
        │
        ▼
  Step Functions:  fetch ──► [Map: extract ──► normalise] ──► FAN-OUT
                     │              │              │             │
                   S3 PDFs      pdfplumber     Bedrock       GSI1 query:
                                /Textract    (schema map)   "whose shelf?"
                                                                 │
                                                                 ▼
                                                        alerts + SES email
```

The red path is the one that matters: a batch gets flagged, the fan-out function asks DynamoDB's
GSI "who has this batch on a shelf?", and an alert lands in someone's hand weeks after they
bought the medicine.

### Data model — one table, one GSI

| Entity | PK | SK | GSI1PK |
|---|---|---|---|
| Shelf item | `USER#<sub>` | `ITEM#<ulid>` | `BATCH#<skeleton>` |
| Alert | `USER#<sub>` | `ALERT#<ts>#<ulid>` | — |
| NSQ row | `BATCH#<skeleton>` | `NSQ#<month>#<hash>` | `DRUG#<generic>` |
| Ingest doc | `SOURCE#CDSCO` | `DOC#<urlhash>` | — |
| Pharmacy job | `JOB#<ulid>` | `META` | — |
| Scan cache | `SCAN#<imagehash>` | `EXTRACT` | — |

Every access pattern is a single query:

- *My shelf* → `PK = USER#x, SK begins_with ITEM#`
- *My alerts, newest first* → `PK = USER#x, SK begins_with ALERT#`, descending
- *Is this batch flagged?* → `PK = BATCH#<skeleton>`
- **Whose shelf holds this newly flagged batch?** → `GSI1PK = BATCH#<skeleton>` ← the product

Scan caches and pharmacy jobs carry a `ttl` attribute and delete themselves.

---

## The matching engine

The interesting part, and the thing worth writing about. Foil print is embossed, low-contrast
and curved; OCR gives you `KPUO21H` when the strip says `KP4021H`.

### Two tiers of glyph confusion

Most systems pick one: either collapse confusable characters (which merges unrelated batch
codes) or don't (which loses damaged reads). BatchWatch models the error channel in two tiers
(`functions/common/python/batchwatch_common/glyph.py`):

- **Hard confusables** — `O/Q/D→0`, `I/L→1`, `S→5`, `B→8`, `Z→2`, `G→6`. Genuinely
  indistinguishable on foil, so they are *collapsed* into a **skeleton** before anything else
  happens. This error disappears for free.
- **Soft confusables** — `4/A`, `7/T`, `U/V`, `K/X`, `M/N`, `3/8` and friends. Similar but still
  separable, so instead of collapsing they are charged **0.3 of a normal substitution** inside a
  weighted Levenshtein distance. An unrelated substitution still costs full price.

This is what lifts recall on damaged reads without spending precision.

### Four weighted signals

| Signal | Weight | Method |
|---|---|---|
| Batch skeleton | 0.55 | exact = 1.0, else OCR-weighted edit similarity |
| Drug name | 0.25 | `token_set_ratio` on generic + strength |
| Manufacturer | 0.15 | `token_set_ratio` after stripping `M/s`, `Ltd`, `Pvt` |
| Expiry agreement | 0.05 | 1.0 within ±1 month, else 0 |

A signal missing from the query has its weight removed and the rest renormalised, so a sparse
query is never silently penalised — just less decisive.

```
score ≥ 0.92  →  FLAGGED     (red)
0.74 – 0.92   →  UNCERTAIN   (amber → ask the model)
score < 0.74  →  NO_MATCH    (green)
```

**A batch code alone can never reach FLAGGED.** Codes are short and collide across
manufacturers, so batch-only evidence is presented for review, never as a verdict. That is why
`/search` returns rows rather than verdicts.

### Retrieval, not just scoring

The first version lost 14% of two-error reads. The cause was candidate *retrieval*, not scoring:
a badly mangled code shares no trigram with its true row, so the right answer was never scored
at all. The index therefore blocks on two keys — the batch skeleton's trigram neighbourhood
**and** the drug's generic molecule. False clears went to zero at one and two errors, and
precision was unaffected: those rows still have to clear the batch-similarity bar, they just get
the chance to be scored.

### Measured behaviour

Against 2,341 rows, 200 sampled medicines per level, OCR damage simulated by `tests/ocr_noise.py`:

| Damage | Auto-flagged | Amber (sent to adjudication) | **False clears** | Wrong row |
|---|---|---|---|---|
| Clean read | 100% | 0% | **0%** | 0 |
| 1 OCR error | 86% | 14% | **0%** | 0 |
| 2 OCR errors | 43% | 57% | **0%** | 0 |
| 3 OCR errors | 17% | 80% | 3% | 0 |

500 unflagged medicines: **0 false flags**, 493 clean greens, 7 amber.
Match latency: ~8 ms over the full corpus, in-process, no database round trip.

These numbers are asserted in `tests/test_match.py`, not just reported here.

### The adjudication step, and one asymmetry

For the amber band, Bedrock gets the cropped strip image plus the two or three candidate rows
and answers one narrow question: *is the batch code on this strip the same code as any of
these?* It returns `match` / `no_match` / `uncertain` plus a one-line reason, which the UI shows.

The asymmetry: adjudication can turn amber into red, but **never into green**. The model ruling
out these particular candidates is not evidence that the medicine is fine. A false clear is the
only failure mode of this app that can hurt someone, so amber stays amber.

---

## About the data

**`data/nsq_seed.jsonl` is synthetic sample data, not real CDSCO alerts.** It exists so the app
is demonstrable before the PDFs are parsed, and stays demonstrable if cdsco.gov.in is slow on
demo morning.

The generic molecules are real (they belong to nobody). **Every manufacturer is invented** —
publishing a fabricated quality failure against a real pharmaceutical company is defamation, not
test data. Every row carries `"synthetic": true`, `/stats` reports the count, and the web app
shows a banner while the corpus is synthetic.

**Before you demo this on camera, load the real thing:**

```bash
python scripts/download_cdsco.py --list            # see what the scraper finds
python scripts/download_cdsco.py --months 18       # or save PDFs into data/pdfs/ by hand
python scripts/build_seed.py --dry-run             # check row counts before spending anything
python scripts/build_seed.py --use-bedrock         # let Claude map the columns
python scripts/load_seed.py
```

`build_seed.py` works without Bedrock (heuristic header mapping) but the LLM path is what
handles the layouts that change between months and between state regulators — which is most of
them.

---

## API

| Route | Auth | Does |
|---|---|---|
| `POST /scan` | optional | base64 image or typed text → extracted fields + verdict + explanation |
| `POST /shelf` | required | save a scanned item |
| `GET /shelf` | required | list items, each re-checked against the current corpus |
| `DELETE /shelf/{id}` | required | remove an item |
| `GET /alerts` | required | retroactive alerts, newest first (`?mark_read=1`) |
| `POST /pharmacy/check` | required | CSV or pasted stock list → job with grouped results |
| `GET /pharmacy/check/{id}` | required | fetch a job (kept 24 h) |
| `GET /search?q=` | public | batch / drug / manufacturer lookup — returns evidence, not a verdict |
| `GET /stats` | public | corpus size, latest alert month, Bedrock status |
| `POST /admin/ingest` | admin key | trigger ingest — the demo's payoff button |

`POST /scan` is deliberately usable without login: making someone sign up before they can see
what the thing does costs more than the auth story gains.

---

## Deploy to AWS

**Full step-by-step runbook: [DEPLOY.md](DEPLOY.md)** — prerequisites, Bedrock model access, budget alert, deploy, corpus load, verification, Amplify, SES, and a
troubleshooting table. The short version:

```bash
sam build --use-container
sam deploy --guided --parameter-overrides \
  "AdminKey=$(openssl rand -hex 16)" \
  "CorsOrigin=https://your-amplify-url" \
  "RequireLogin=true"
```

Then point the web app at the API (`web/.env`: `VITE_API_BASE=https://…`), build, and connect
`web/` to Amplify Hosting.

Services used: Lambda, API Gateway HTTP API, DynamoDB (+ GSI), S3, Bedrock, Textract, Step
Functions, EventBridge Scheduler, Cognito, SES, Amplify, SAM.

**`RequireLogin`** is the parameter to understand. With `false` (default) the shelf routes are
open at the gateway and the caller is identified by an `X-Device-Id` header — that is a
*namespace, not a security boundary*. Anyone holding the device id can read that shelf. Fine for
a demo on your own phone; set it to `true` — which puts those routes behind the Cognito JWT
authorizer — before anyone else stores their medicines in it.

**Cost guardrails.** Set an AWS Budgets alert at $20 *before* deploying. Lambda, API Gateway,
DynamoDB and S3 sit inside the free tier at demo volumes; the real variable is Bedrock. Images
are downscaled to 1400px on-device before upload and extraction results are cached by image
hash, which cuts per-scan cost by roughly an order of magnitude. There is deliberately **no
OpenSearch**: it has a minimum-capacity floor that bills continuously (~$15–20/day) whether you
query it or not, and at this corpus size the in-Lambda index is faster anyway.

---

## Testing

```bash
python -m pytest              # 139 tests
python -m pytest -q tests/test_match.py    # the engine numbers above
```

The suite runs with no AWS account and no network. Notable tests:

- `test_match.py` — the OCR-damage table above, asserted; false clears forbidden
- `test_fuzz.py` — the pure-Python similarity fallback must agree with rapidfuzz *exactly*, so a
  Lambda without the compiled wheel scores identically to CI
- `test_api.py::test_a_recall_published_later_reaches_the_shelf` — the whole product in one test
- `test_ingest.py::test_deep_fanout_catches_a_mis_read_batch_on_the_shelf`
- `test_bedrock.py` — degradation and the circuit breaker, no live calls

---

## Privacy and safety

A list of someone's medicines is health data about them and often about their family.

- Scan images are processed **in memory** and never persisted; only extracted text is cached,
  under a 24-hour TTL, keyed by image hash.
- Shelf entries store drug name, batch and expiry. Never a prescription, a doctor, or a
  condition.
- One IAM role per Lambda, scoped to the specific table and bucket prefix. No wildcard resources
  except the Bedrock and Textract service actions.
- `POST /scan` is rate-limited at the API Gateway stage — an open vision endpoint is a bill
  waiting to happen.
- A permanent disclaimer, returned by the API itself so it cannot be dropped by a client: this
  reflects published regulator alerts only, is not a certification of authenticity, and is not
  medical advice. **"Not flagged" means this batch is absent from the alerts we hold — not that
  the medicine is safe.**

Severity maps to language a patient can act on:

| Severity | Classes | What the user is told |
|---|---|---|
| CRITICAL | SPURIOUS, STERILITY, ENDOTOXIN, CONTAMINANT | Stop taking this. Contact your doctor and the pharmacy. |
| HIGH | ASSAY, DISSOLUTION, IDENTIFICATION | May be weaker than labelled. Speak to your doctor before your next dose. |
| MODERATE | MICROBIAL, PARTICULATE, pH | Failed a quality test. Return it to the pharmacy. |
| LOW | DESCRIPTION, OTHER | A labelling or appearance standard was not met. |

Verdict copy ships in English, Hindi and Tamil.

---

## Known limitations

Worth stating out loud; each is a deliberate boundary, not an oversight.

1. **Bedrock paths have not been executed against live Bedrock.** The build environment has no
   resolvable AWS credentials. The request shapes are written against the current documented SDK
   surface (`AnthropicBedrockMantle`, `anthropic.`-prefixed model ids, `output_config` structured
   outputs) and asserted in `test_bedrock.py` against a fake client, but the first real call is
   still unproven. Everything degrades cleanly if it fails: vision falls back to the typed-text
   parser, column mapping falls back to the heuristic header reader, adjudication is skipped and
   amber stays amber.
2. **The SAM template has not been deployed.** No SAM CLI in this environment. YAML, resource
   structure, route wiring, IAM policy shapes and the state machine (including substitution names
   and transition targets) are validated programmatically; a first `sam deploy` may still need
   small corrections.
3. **The CDSCO fetch scraper is untested against the live site.** The site has no
   machine-readable index and reorganises periodically. `--list` shows what it finds before
   downloading, and saving PDFs into `data/pdfs/` by hand is a first-class path.
4. **Deep fan-out is O(shelf items).** The exact GSI lookup is O(1) per flagged batch and is the
   designed path, but it misses shelf entries whose batch was mis-read at scan time (different
   skeleton). The `deep` sweep re-scores every shelf item and catches those. Correct at demo
   scale; at national scale it becomes a per-molecule sweep using the `DRUG#<generic>` GSI
   partition that is already written.
5. **No SMS.** Transactional SMS to Indian numbers needs DLT registration with the telecom
   regulator and a template approval cycle measured in days. In-app plus SES email only.
6. **SES starts in sandbox** — verify your own address before the demo or email silently
   no-ops (in-app alerts still work).

---

## Repo map

```
template.yaml                SAM: table, GSI, API, functions, state machine, schedule
statemachine/ingest.asl.json fetch → [extract → normalise] → fan-out
data/
  nsq_seed.jsonl             the corpus (synthetic sample by default)
  nsq_holdback.jsonl         the month held back for the demo
  pdfs/                      CDSCO PDFs you download
functions/
  common/python/batchwatch_common/
    glyph.py                 two-tier OCR confusion model + weighted edit distance
    normalise.py             batch/date/drug/manufacturer normalisation, skeletons
    match.py                 weighted scoring, verdict bands, the in-memory index
    fuzz.py                  rapidfuzz with an exact pure-Python fallback
    labelparse.py            label reader with no model in the loop
    bedrock.py               Claude: vision, column mapping, adjudication
    ingest.py                extract / normalise / fan-out
    repo.py  store.py        single-table access patterns, DynamoDB + local drivers
    verdict.py               match → something you can say to a person
    schema.py  notify.py  cdsco.py  blob.py  http.py  ids.py
  scan/ shelf/ search/ pharmacy/ admin/ ingest/{fetch,extract,normalise,fanout}/
scripts/
  make_sample_seed.py        generate the synthetic corpus
  download_cdsco.py          fetch the real PDFs
  build_seed.py              PDFs → nsq_seed.jsonl
  load_seed.py               jsonl → the table, with --holdback-month
  serve_local.py             run the real handlers locally, no AWS
  verify_deploy.py           walk the whole product against any base URL
tests/                       139 tests, no network, no AWS
web/                         Vite + React + TypeScript + Tailwind PWA
```

`normalise.py` and `match.py` live in the shared layer and are imported by **both** the scan
path and the fan-out path. If the two ever disagree about what skeleton a batch code produces,
the reverse lookup silently returns nothing — which is why there is exactly one implementation.
