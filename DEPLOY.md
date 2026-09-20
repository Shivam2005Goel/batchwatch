# Deploying BatchWatch to AWS

Everything you have to do, in order. Roughly 45–90 minutes the first time, most of it waiting
for Bedrock model access to be granted.

Each step ends with something you can check, so you never move on from a broken step.

---

## What you set up vs what the template sets up

Start here, because it is less work than it looks. **`sam deploy` creates 16 resources for you.**
You only touch the AWS console for five things, and only one of them is mandatory.

### Created automatically by `template.yaml` — do not create these by hand

| Service | Resource | Notes |
|---|---|---|
| DynamoDB | `batchwatch-<stage>` table + `GSI1` | on-demand, TTL on `ttl`, PITR, encrypted |
| S3 | `batchwatch-raw-<stage>-<account>` | public access blocked; 90-day PDF lifecycle |
| API Gateway | HTTP API + all 10 routes + throttling | JWT authorizer wired to the user pool |
| Lambda | 9 functions + 1 shared layer | scan, search, shelf, pharmacy, admin, 4× ingest |
| Cognito | user pool + app client | created even when `RequireLogin=false` |
| Step Functions | `batchwatch-ingest-<stage>` state machine | fetch → [extract → normalise] → fan-out |
| EventBridge Scheduler | monthly ingest schedule | 1st, 8th, 15th at 06:00 UTC |
| IAM | one scoped execution role per function | no wildcard resources |
| CloudWatch Logs | one log group per function | automatic |

### You set up by hand

| # | Service | Mandatory? | Why it cannot be in the template |
|---|---|---|---|
| 1 | **AWS account + IAM credentials** | Yes | you need creds before CloudFormation can run |
| 2 | **Bedrock model access** | **Yes, for the vision path** | a per-account approval, not a deployable resource |
| 3 | **AWS Budgets alert** | Strongly advised | protects you from your own stack |
| 4 | **SES identity verification** | Only for email alerts | AWS must email you to prove you own the address |
| 5 | **Amplify Hosting app** | Only for the public URL | connects to your GitHub repo |

**Textract, CloudWatch, S3, DynamoDB, Step Functions and EventBridge need no enablement at all** —
they activate on first use, and the template already grants the IAM actions
(`textract:AnalyzeDocument`, `bedrock:InvokeModel`, `ses:SendEmail`).

So the honest answer to "what services must I set up": **Bedrock model access, and an IAM user.**
Everything else is either automatic or optional.

---

## 0. Install the tooling

You already have AWS CLI, git, Node and Python. Two things are missing:

| Tool | Why | Get it |
|---|---|---|
| **AWS SAM CLI** | builds and deploys the stack | <https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html> |
| **Docker Desktop** | **required** — see below | <https://www.docker.com/products/docker-desktop/> |

**Docker is not optional here.** Four dependencies ship compiled binaries — `rapidfuzz`,
`pydantic-core` (via `anthropic`), `Pillow` and `pypdfium2` (via `pdfplumber`). Building on
Windows produces `win_amd64` wheels, which Lambda's Linux runtime cannot load. You would deploy
successfully and then get `ImportError` on the first invocation. `sam build --use-container`
builds inside a Lambda-like Linux image and produces the right wheels.

*Alternative if you cannot install Docker:* run steps 4–5 from AWS CloudShell or any Linux box
(`git clone` your repo there, install SAM, `sam build` without `--use-container`). The build must
happen on Linux one way or another.

Check:

```bash
sam --version
docker --version && docker ps
```

`docker ps` must succeed — Docker Desktop has to be *running*, not just installed.

---

## 1. AWS account and IAM credentials

If you do not have an account: <https://portal.aws.amazon.com/billing/signup>. It needs a card
even though everything here sits in or near the free tier. Account creation can take a few
minutes to finish activating.

**Do not deploy as the root user.** Create an IAM user:

1. **IAM console** → **Users** → **Create user**
2. Name it `batchwatch-deploy`. Do **not** tick "Provide user access to the console" — this user
   only needs API access.
3. **Set permissions** → **Attach policies directly** → **`AdministratorAccess`**.

   For a hackathon account this is the pragmatic choice, and it is what I would use. If you need
   it scoped, the deploying principal needs: `cloudformation:*`, `lambda:*`, `dynamodb:*`,
   `s3:*`, `apigateway:*`, `cognito-idp:*`, `states:*`, `scheduler:*`, `logs:*`, `ses:*`,
   plus `iam:CreateRole`, `iam:DeleteRole`, `iam:AttachRolePolicy`, `iam:DetachRolePolicy`,
   `iam:PutRolePolicy`, `iam:DeleteRolePolicy`, `iam:GetRole`, `iam:PassRole` and
   `iam:TagRole` — SAM creates one execution role per function, so role creation is not
   optional.
4. Open the created user → **Security credentials** → **Create access key** → choose
   **Command Line Interface (CLI)** → copy the key id and secret.

Then:

```bash
aws configure
```

Give it the key id, the secret, your chosen region (e.g. `ap-south-1`), and `json`.

Check:

```bash
aws sts get-caller-identity
```

It must print your account id and the `batchwatch-deploy` ARN. Right now on this machine it
prints `Unable to locate credentials`.

> **Note for later:** these are long-lived keys on your laptop. Delete the access key in the IAM
> console once the hackathon is over.

---

## 2. Pick your regions, and enable Bedrock model access

Two regions matter and **they do not have to be the same**:

- **Stack region** — where Lambda, DynamoDB, API Gateway live. Pick what you like;
  `ap-south-1` (Mumbai) is the natural choice for an Indian project and keeps latency low.
- **Bedrock region** (`BedrockRegion` parameter) — must be a region where you have been granted
  access to the Claude model. `us-east-1` is the safe default.

**This is the only service with a mandatory manual gate, so do it first — the approval is what
you will be waiting on.**

1. Switch the console region picker (top right) to your **Bedrock region**, e.g. `us-east-1`.
2. **Bedrock console** → left sidebar, bottom → **Model access**.
3. Click **Modify model access** (or **Enable specific models** on a fresh account).
4. Tick the **Anthropic** Claude models. Submit.
5. Anthropic models usually require a short **use case details** form — company name, use case.
   Fill it honestly: *"Hackathon project: reading medicine batch codes from photographs and
   mapping regulator PDF tables to a fixed schema."*
6. Wait for each model's status to read **Access granted**. Usually minutes; occasionally longer.

If Claude is not offered in your region's list at all, that region does not carry it — switch the
picker to `us-east-1` and use that as your `BedrockRegion`. The app calls Bedrock cross-region,
so your stack can still live in `ap-south-1`.

Then confirm the exact model id available to you:

```bash
aws bedrock list-foundation-models --region us-east-1 \
  --query "modelSummaries[?contains(modelId,'anthropic')].modelId" --output table
```

The template defaults to `anthropic.claude-opus-5`. **If that id is not in the list, pass the id
that is** via `--parameter-overrides BedrockModel=<id>` in step 4. Bedrock model ids carry the
`anthropic.` provider prefix — that prefix is expected, not a typo.

> If you skip this step entirely the stack still deploys and the app still works: photo scanning
> falls back to "type the label instead", and PDF column mapping falls back to the heuristic
> header reader. You lose the vision path, not the product.

---

## 3. Set a budget alert *before* you deploy

1. **Billing and Cost Management** console → **Budgets** → **Create budget**.
2. Choose **Customize (advanced)** → **Cost budget**.
3. Period **Monthly**, budget amount **$20**, type **Fixed**.
4. Add an alert threshold at **80% of budgeted amount**, actual cost, and put your email in.
5. Confirm the subscription email AWS sends you.

Do this before deploying, not after. Lambda, DynamoDB, S3 and API Gateway sit inside the free
tier at demo volumes; Bedrock is the variable one, and an open `/scan` endpoint is a bill waiting
to happen (which is why the template throttles that route to 5 rps).

> Budgets data lags by up to a day. It is a safety net, not a live meter — check the Bedrock
> usage page directly if you are worried mid-build.

---

## 4. Build and deploy the stack

From the repo root:

```bash
# Windows PowerShell - generate an admin key and keep it somewhere
$AdminKey = -join ((48..57) + (97..102) | Get-Random -Count 32 | % {[char]$_})
echo $AdminKey

sam build --use-container

sam deploy --guided `
  --parameter-overrides "AdminKey=$AdminKey" "BedrockRegion=us-east-1" "Architecture=x86_64"
```

On bash: `ADMIN_KEY=$(openssl rand -hex 16)` and swap the quoting.

At the `--guided` prompts:

| Prompt | Answer |
|---|---|
| Stack Name | `batchwatch` |
| AWS Region | your stack region, e.g. `ap-south-1` |
| Confirm changes before deploy | `y` |
| Allow SAM CLI IAM role creation | **`y`** |
| Disable rollback | `n` |
| `AdminFunction` has no authorizer, is this okay? | **`y`** — `/admin/ingest` is protected by the `x-admin-key` header, not the gateway |
| `ScanFunction` / `SearchFunction` no authorizer | **`y`** — these are deliberately public |
| Save arguments to samconfig.toml | `y` — safe, `samconfig.toml` is gitignored precisely because this prompt writes your `AdminKey` into it |

Parameters worth knowing:

| Parameter | Default | Notes |
|---|---|---|
| `AdminKey` | — | required, min 16 chars. This is your demo trigger. |
| `BedrockModel` | `anthropic.claude-opus-5` | override with whatever step 2 listed |
| `BedrockRegion` | `us-east-1` | where model access was granted |
| `Architecture` | `x86_64` | `arm64` is ~20% cheaper but needs QEMU emulation to build on an x86 laptop. Switch after the first deploy works. |
| `RequireLogin` | `false` | **leave false** — see step 8 |
| `CorsOrigin` | `*` | tighten in step 7 |
| `SesFromAddress` | empty | email off; in-app alerts still work |

Check — save these, you need them next:

```bash
aws cloudformation describe-stacks --stack-name batchwatch \
  --query "Stacks[0].Outputs" --output table
```

You want `ApiUrl` and `TableName`.

---

## 5. Load the corpus into DynamoDB

The stack creates an empty table. Fill it from your machine (this is pure boto3, so no Docker
and no Linux needed):

```bash
# PowerShell
$env:BW_STORE="dynamodb"
$env:BW_TABLE="batchwatch-dev"        # the TableName output from step 4
$env:AWS_REGION="ap-south-1"          # your stack region

python scripts/load_seed.py --holdback-month 2026-08
```

The `--holdback-month` is deliberate: it keeps one month out of the database so you have
something to publish live during the demo.

Check:

```bash
curl "<ApiUrl>/stats"
```

`rows` should be about 2210 and `bedrock.available` should be `true`.

---

## 6. Verify the deployment properly

```bash
python scripts/verify_deploy.py --base "<ApiUrl>" --admin-key "<your AdminKey>"
```

This walks the entire product against the live URL — scan, save, ingest the held-back month,
assert the alert arrives, assert the shelf turns red, pharmacy check, and a deliberately
mis-read batch code. Ten checks, pass/fail each.

**Check 6 is the one that matters.** If it passes on your deployed URL, the deployment is real.

Locally right now it prints:

```
PASS  6. the alert reaches the shelf item with no further user action
      >>> Ciprofloxacin Tablets IP 500mg  batch 472717
PASS  7. GET /shelf now reads FLAGGED
```

If a check fails the script tells you what it means (403 → wrong admin key, 401 → the shelf
routes want a Cognito token, stale shelf verdict → the corpus version marker did not get
written).

---

## 7. Put the web app on Amplify Hosting

Amplify's Git flow needs the code on GitHub:

```bash
git add -A
git commit -m "BatchWatch"
gh repo create batchwatch --private --source=. --push
```

Then:

1. **Amplify console** → **Create new app** → **Deploy your app** → **GitHub**.
2. Authorise AWS Amplify on GitHub (it asks for repo access — you can scope it to this one repo).
3. Pick the `batchwatch` repo and the `main` branch.
4. On the build settings screen, set **app root / base directory** to **`web`**. Amplify usually
   auto-detects Vite from `web/package.json`; if it does not, the build spec is:

   ```yaml
   version: 1
   applications:
     - appRoot: web
       frontend:
         phases:
           preBuild:
             commands: [npm ci]
           build:
             commands: [npm run build]
         artifacts:
           baseDirectory: dist
           files: ['**/*']
         cache:
           paths: [node_modules/**/*]
   ```

5. **Advanced settings** → **Environment variables** → add `VITE_API_BASE` = your `ApiUrl`
   (no trailing slash).
6. **Save and deploy.**

`VITE_API_BASE` is baked in at build time by Vite, not read at runtime. If you change it you must
**redeploy the branch**, not just save the variable — this catches people out.

Amplify gives you a URL like `https://main.d1234.amplifyapp.com`. **Now go back and lock down
CORS**, which is currently `*`:

```bash
sam deploy --parameter-overrides "AdminKey=$AdminKey" "CorsOrigin=https://main.d1234.amplifyapp.com"
```

Check: open the Amplify URL on your phone, scan a strip, see a verdict.

---

## 8. Authentication — read this before flipping `RequireLogin`

The stack creates a Cognito user pool and a JWT authorizer, and the API supports them. **The web
app has no login screen.** It sends `Authorization: Bearer <token>` if one happens to be in
`localStorage["bw.token"]`, and otherwise identifies the caller by an `X-Device-Id` header.

So:

- **`RequireLogin=false`** (the default) — everything works from the browser today. The device id
  is a *namespace, not a security boundary*: anyone holding it could read that shelf. Fine for a
  demo on your own phone.
- **`RequireLogin=true`** — the shelf and pharmacy routes go behind Cognito, and the web app's
  shelf will start returning 401 until someone builds a login flow (Amplify UI Authenticator is
  the shortest path, roughly an afternoon).

For the hackathon: deploy with `false`, and say out loud in the video that Cognito is wired and
the switch is one parameter. That is a stronger answer than a half-finished login screen.

To test the authenticated path without a UI, create a user and mint a token:

```bash
aws cognito-idp admin-create-user --user-pool-id <UserPoolId> --username you@example.com
aws cognito-idp admin-set-user-password --user-pool-id <UserPoolId> \
  --username you@example.com --password 'Str0ngpass' --permanent
aws cognito-idp initiate-auth --auth-flow USER_PASSWORD_AUTH \
  --client-id <UserPoolClientId> \
  --auth-parameters USERNAME=you@example.com,PASSWORD='Str0ngpass'
```

Pass the resulting `IdToken` to `verify_deploy.py --token <IdToken>`.

> `USER_PASSWORD_AUTH` is not in the app client's enabled flows by default (only SRP and refresh).
> Add `ALLOW_USER_PASSWORD_AUTH` to `ExplicitAuthFlows` in `template.yaml` if you want this
> shortcut, and take it out afterwards.

---

## 9. Email alerts through SES (optional)

SES starts every new account in **sandbox**, where you can only send **to** addresses you have
verified, and are capped at 200 messages a day. For a demo that is fine — verify your own
address and one teammate's.

Console route: **SES** → **Identities** → **Create identity** → **Email address** → enter it →
AWS emails you a link you must click. Or:

```bash
aws ses verify-email-identity --email-address you@example.com --region <stack region>
aws ses verify-email-identity --email-address teammate@example.com --region <stack region>
```

Verify **both the sender and every recipient** while in sandbox. Check status:

```bash
aws ses list-identities --region <stack region>
aws ses get-identity-verification-attributes --identities you@example.com --region <stack region>
```

You want `VerificationStatus: Success`. Then redeploy with the sender set:

```bash
sam deploy --parameter-overrides "AdminKey=$AdminKey" "SesFromAddress=you@example.com"
```

Email also needs a profile row carrying the address for the user — anonymous device-id shelves
have no address and simply get the in-app alert, which is the intended behaviour. To give
yourself one:

```bash
aws dynamodb put-item --table-name batchwatch-dev --item '{
  "PK": {"S": "USER#d_<your device id>"},
  "SK": {"S": "PROFILE"},
  "type": {"S": "PROFILE"},
  "email": {"S": "you@example.com"}
}'
```

Your device id is in the browser: DevTools → Application → Local Storage → `bw.device`. The
stored key is `d_<that value>`.

Leaving sandbox needs a **production access** request (SES → Account dashboard → Request
production access), which is reviewed by AWS and is not worth starting for a weekend demo.

There is deliberately no SMS: transactional SMS to Indian numbers needs DLT registration with
TRAI and a template approval cycle measured in days.

---

## 10. Load the real CDSCO data

The corpus shipped in the repo is **synthetic sample data with invented manufacturers** —
publishing a fabricated quality failure against a real pharmaceutical company is defamation, not
test data. Every row is tagged `synthetic: true` and the app shows a banner while that is the
case.

**Do this before you record anything.**

```bash
python scripts/download_cdsco.py --list           # see what the scraper finds first
python scripts/download_cdsco.py --months 18      # or save PDFs into data/pdfs/ by hand
python scripts/build_seed.py --dry-run            # row counts, spends nothing
python scripts/build_seed.py --use-bedrock        # needs AWS creds + model access
python scripts/load_seed.py --holdback-month <the most recent month>
```

The scraper is untested against the live site — CDSCO has no machine-readable index and
reorganises periodically. If `--list` comes back thin, saving the monthly alert PDFs into
`data/pdfs/` by hand is a fully supported path and `build_seed.py` does not care where they came
from.

`--use-bedrock` is what handles the layouts that change between months and between state
regulators. Without it you get the heuristic header reader, which works on tidy tables only.

---

## 11. The monthly schedule is live once you deploy

The stack creates an EventBridge schedule that runs the ingest pipeline on the 1st, 8th and 15th
at 06:00 UTC. It is idempotent (documents already seen by URL hash are skipped) but it *will*
call Bedrock when it finds new PDFs.

To pause it while you are iterating:

```bash
aws scheduler list-schedules
aws scheduler update-schedule --name <name> --state DISABLED \
  --schedule-expression "cron(0 6 1,8,15 * ? *)" --target ... --flexible-time-window ...
```

Simpler: comment out the `Events: Monthly:` block in `template.yaml` and redeploy until you are
ready.

---

## 12. Demo-day checklist

- [ ] `verify_deploy.py` passes all 10 checks against the live URL
- [ ] Real CDSCO corpus loaded, `corpus_is_synthetic` is `false` in `/stats`
- [ ] A month held back, and you know which medicine you are going to scan
- [ ] Admin key in your clipboard / a scratch file, ready to paste
- [ ] A real medicine strip in your hand whose batch is genuinely in the corpus
- [ ] Step Functions console open on a *successful past execution* — judges want to see it ran
- [ ] Phone on the Amplify URL, not localhost
- [ ] Screen recording and voiceover recorded **separately**

---

## 13. Tearing it down

```bash
sam delete --stack-name batchwatch
```

The S3 bucket must be emptied first if it has objects. The DynamoDB table has
`DeletionPolicy: Delete`, so **its data goes with it** — export anything you want to keep first.
Delete the Amplify app separately in its console.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `ImportError: ... rapidfuzz` / `pydantic_core` in Lambda logs | built on Windows without a container | `sam build --use-container` |
| `sam build` fails on arm64 | QEMU emulation | `--parameter-overrides Architecture=x86_64` |
| `/stats` shows `bedrock.available: false` | model access not granted, or wrong region | step 2; check `bedrock.error` in `/stats` |
| `AccessDeniedException ... bedrock:InvokeModel` | model access pending | wait for **Access granted** in the console |
| `ValidationException ... model identifier` | wrong model id for that region | `aws bedrock list-foundation-models`, override `BedrockModel` |
| Scan returns 503 "type the label text instead" | vision unavailable; this is the designed fallback | fix Bedrock, or use the typed-text path |
| Shelf returns 401 | `RequireLogin=true` with no login UI | redeploy with `false`, or pass a token |
| `/admin/ingest` returns 403 | wrong `x-admin-key` | use the `AdminKey` you deployed with |
| Alert arrives but shelf still green | warm Lambda on a stale corpus | the ingest writes `SOURCE#CDSCO / INDEX_VERSION`; confirm the row exists |
| CORS errors in the browser | `CorsOrigin` still `*` or stale | redeploy with the exact Amplify origin |
| `/stats` shows 0 rows | corpus never loaded into DynamoDB | step 5 |
