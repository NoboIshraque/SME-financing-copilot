# Put DecisionGuard online for free (Render, no card, no PC)

For: Nobo. Result: a public link such as `https://decisionguard-web.onrender.com` (or
`https://hishab.quadbits.net`) with the live app and the five synthetic demo shops.

**What you need:** the GitHub account that owns the repo, and a browser. No card, no server, no
PC left switched on. About 30 minutes, most of it waiting for builds.

**How it works:** the repo now has a `render.yaml` "Blueprint". Render reads it and creates three
things on its free plan, in Singapore:

| Piece | What it is |
| --- | --- |
| `decisionguard-db` | a free PostgreSQL database |
| `decisionguard-api` | the API (our Docker image). On every start it loads the demo shops, then serves |
| `decisionguard-web` | the web app. It forwards every `/api/...` request to the API, so the browser sees one address |

We rehearsed the exact start command against PostgreSQL on 20 Oct (demo shops load in about 6
seconds; sign-in, alerts and the foreign-site block all worked). Render itself could not be
tested from our side, so follow the checks in step 5.

---

## 1. Create the Render account (3 min)

1. Open https://render.com and click **Get Started** (or **Sign up**).
2. Choose **GitHub**. Sign in as **NoboIshraque**.
3. When GitHub asks which repositories Render may see, choose **Only select repositories** →
   `SME-financing-copilot` → **Install / Authorize**. (The repo can stay private.)
4. If Render asks for a card, you are on a paid plan page: go back and pick the **Hobby / Free**
   option. The free plan does not need a card.

## 2. Create everything from the Blueprint (2 min + 10–15 min waiting)

1. In the Render dashboard click **New +** → **Blueprint**.
2. Pick the repository `SME-financing-copilot`, branch **main**. Render finds `render.yaml` and
   lists `decisionguard-db`, `decisionguard-api` and `decisionguard-web`.
3. Blueprint name: `decisionguard`.
4. It asks for two values: `GEMINI_API_KEY` and `GROQ_API_KEY`. You may leave both **empty**: the
   app then uses its recorded answers (`LLM_MODE=fixtures`), and every number still comes from our
   engines. (To use the real models later, see step 7.)
5. Click **Apply**. Render builds the API (about 10 minutes; it is a Docker image) and the web app
   (about 3 minutes). Watch each service's **Logs** tab.
6. Done when both services show **Live**. In the API's logs you should see five lines like
   `seeded sme_hardware: 4445 transactions (synthetic)` and then `Uvicorn running`.

## 3. Check the two addresses match (2 min) — important

Render names each service after the Blueprint if the name is free. If someone already took
`decisionguard-api` or `decisionguard-web`, Render adds letters, and the two must be told about
each other:

1. Open **decisionguard-api**. Its address is at the top, e.g.
   `https://decisionguard-api.onrender.com`. Write it down.
2. Open **decisionguard-web**. Its address, e.g. `https://decisionguard-web.onrender.com`. Write
   it down.
3. If the API address is **not** `https://decisionguard-api.onrender.com`: in **decisionguard-web**
   → **Redirects/Rewrites**, edit the rule with source `/api/*` so its destination is
   `<your API address>/api/*`. Save.
4. If the web address is **not** `https://decisionguard-web.onrender.com`: in
   **decisionguard-api** → **Environment**, set `CORS_ORIGINS` to your web address (no slash at the
   end). Save; the API restarts.

## 4. Open it (1 min)

1. Open the **web** address in a browser.
2. On the sign-in page use **Try the demo** → **Sign in as Owner** on **Nawabpur Hardware
   Traders**. The next screen shows the demo code to type.
3. The Today screen should show a **Critical** cash alert for the hardware shop.

**Judges' own shops.** The sign-in page also offers **create your own shop**. A judge picks a
shop name, email and password, lands on **Settings → Set up your shop**, types the opening cash
balance and its date, downloads the example file (or uses their own CSV/Excel), uploads it, and
every screen then runs on those numbers: no synthetic banner for that shop. Approvals need them
to set up an approval code there with any authenticator app.

## 5. If something is wrong

| What you see | Why | Fix |
| --- | --- | --- |
| The page loads but sign-in says "origin not allowed" (403) | `CORS_ORIGINS` does not match the web address | Step 3.4 |
| Every screen errors, or `/api/health` gives 404 on the web address | The `/api/*` rewrite points at the wrong API name | Step 3.3 |
| The first visit takes about a minute | The free API sleeps after 15 minutes without visitors and wakes on the next request | Normal. Open the link 2 minutes before you record or before judges look |
| Today says there is not enough data | The demo shops did not load | API → **Logs**: look for the `seeded …` lines. **Manual Deploy** → **Restart service** reloads them |
| API build fails | Render build error | API → **Events** → open the failed deploy, copy the last 30 log lines, and give them to the orchestrator |

Health check: `<API address>/api/health` should show `"status":"ok"`, `"app_env":"demo"` and
`"database":"postgresql"`.

## 6. Our own domain (optional, 10 min + DNS wait; better for China)

1. **decisionguard-web** → **Settings** → **Custom Domains** → **Add** → `hishab.quadbits.net`.
   Render shows a CNAME target (the web address without `https://`).
2. Namecheap → **Domain List** → `quadbits.net` → **Manage** → **Advanced DNS** → **Add new
   record**: type **CNAME**, host `hishab`, value the target from step 1, TTL automatic. Remove any
   older `A` record for `hishab`.
3. Wait until Render shows the domain as verified with a certificate (5–60 minutes).
4. **decisionguard-api** → **Environment** → `CORS_ORIGINS` =
   `https://decisionguard-web.onrender.com,https://hishab.quadbits.net` (your web address first,
   comma, no spaces). Save.
5. Check from China: open https://www.17ce.com, paste `https://hishab.quadbits.net`, run the
   test, and look at the mainland China rows. Mostly green means judges can open it.

## 7. Real AI models (optional)

**decisionguard-api** → **Environment**: set `LLM_MODE` to `live`, and fill `GEMINI_API_KEY` and
`GROQ_API_KEY` with the keys from your password manager (type them yourself; never paste them
into a chat or a file). Save. The copilot then asks the models, still through the privacy
gateway; numbers still come from the engines.

## 8. Limits to know (say them if asked)

- Free API: 512 MB memory, sleeps when idle, wakes in about a minute.
- Free database: Render deletes free databases after a fixed period (30 days at our last check;
  the dashboard shows the date). Enough for judging; after that, the demo shops reload into a new
  database by creating it again from the Blueprint.
- The background worker (daily alert scan, nightly audit anchor) is not part of the free setup.
  The screens, approvals and copilot do not need it.
- Anyone can sign in as a demo user: that is demo mode, synthetic shops only (security
  self-assessment R5).
- Updates: the Blueprint has auto-deploy off, so the demo does not change under you. To ship a
  new `main`: each service → **Manual Deploy** → **Deploy latest commit**.
