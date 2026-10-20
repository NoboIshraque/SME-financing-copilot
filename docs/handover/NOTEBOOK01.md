# Notebook 01: the real-data forecast backtest

For: Nobo and Labib. The notebook is written and on `main`:
`ml/notebooks/01_forecast_backtest.py` (source of truth) and `ml/notebooks/01_forecast_backtest.ipynb`
(the same code as a Jupyter notebook). It has **never been run**: the orchestrator's cloud
session could not download the dataset. `docs/packages/WP-17.md` milestone 1 and the technical
documentation (§3.3, "has not produced results yet") are waiting for it.

---

## Part 1. What this is, in plain words

### The question

DecisionGuard warns a shop owner **before** the cash runs short. All our own tests use shops
that **our code invented** (the synthetic universe). A judge can fairly ask: "Does your kind of
forecaster also work on real data you did not make?" This notebook answers that question with
numbers.

### The data

**UCI Online Retail II**: every sale of a real UK online gift shop from 1 Dec 2009 to
9 Dec 2011, about a million rows, published by the UCI Machine Learning Repository under the
CC BY 4.0 licence (free to use with credit). It is not a Bangladeshi shop, but it is real
money from a real small business, with weekly patterns and a Christmas peak.

The notebook adds up each day's sales (refunds count as minus) to get "cash in per day". A
real shop also pays money out, so the notebook adds a simple, fixed bill schedule: a supplier
payment every Monday (95% of a normal week's sales) and rent on the 1st of each month (4 days
of sales). A **cash gap** is a day the balance drops below a safety buffer of 3 days of sales.

### Three forecasters are compared

| Name | In plain words |
| --- | --- |
| Seasonal naive | "Next Monday will look like last Monday." The simplest honest baseline |
| ETS (Holt-Winters) | A classic statistics method that follows the level, trend and weekly pattern |
| LightGBM quantile | A machine-learning model that learns from calendar features and older sales |

Each one gives three numbers per day: a low case (P10), a likely case (P50) and a high case
(P90). That is a **band**, like the band on our Cash screen.

### Walk-forward and "no leakage"

Imagine standing on 1 March 2011 with only the sales up to 28 February. You forecast the next
28 days. Then you step 14 days forward and do it again, and so on until November 2011: about
19 "origins" (forecast days) per model. Each forecast may use **only** what was known on its
origin day. Using even one day from the future would be **leakage**: the test would look
better than reality. The LightGBM model only uses sales at least 28 days old, so nothing from
the forecast window can sneak in.

### What comes out

Two files in a folder `hishab_ml/`:

1. `forecast_backtest.json`: the summary. Per model:
   - `wape_mean`: average size of the daily error, as a share of actual sales (lower is better).
   - `weekly_mape_mean`: the same idea per week.
   - `coverage_80_mean`: how often the real day fell inside the P10–P90 band. An honest band
     scores near **0.8** (80%).
   - `pinball_mean`: one score for the whole band (lower is better). The model with the lowest
     one becomes `chosen_model`.
   - `gaps`: for three starting cushions (0.5, 1 and 2 days of sales above the low point):
     `real_gaps` (how many real gaps happened), `gap_hit_rate` (share of real gaps the model
     warned about **before** they happened), `false_alarm_rate` (warnings when no gap came),
     `mean_lead_time_days` (how many days of warning, on average).
2. `forecast_backtest_origins.csv`: one row per origin and model, with the same measures, so
   anyone can check the summary.

The file also records `"data_mode": "public"`: this is real **public** data, not synthetic and
not "our shops".

### Why the judges care

It turns "trust us" into a measured, reproducible claim on data we did not generate: how
often the forecaster warns before a gap, how early, and how often it cries wolf. Whatever the
numbers are, good or bad, we report them as they come out. We never edit them.

---

## Part 2. Fastest path: let the orchestrator run it

The cloud session only lacks network access to one host: `archive.ics.uci.edu` (the notebook
downloads `https://archive.ics.uci.edu/static/public/502/online+retail+ii.zip`). Python
packages come from the package managers, which are already allowed.

1. Open the orchestrator's session on claude.ai/code.
2. In the session **title bar**, open the **cloud environment** menu → **Edit**.
3. **Network access** → choose **Limited**.
4. Under **Allowed domains**, add: `archive.ics.uci.edu`
5. Keep **Allow package managers** ticked.
6. **Save**. (Docs: https://code.claude.com/docs/en/cloud-environments#network-access)
7. In the session, type: **run notebook 01**

The orchestrator then runs it (Part 4 shows the steps it follows), commits the two result files
on a branch and opens a pull request. If the download still fails, use Part 3.

---

## Part 3. Do it yourself on Kaggle (about 30 minutes)

No GPU and no internet are needed: the dataset is attached inside Kaggle.

### 3.1 Kaggle account

1. Go to `https://www.kaggle.com` → **Register** (or **Sign in** with Google or email).
2. Phone verification (Profile → Settings → **Phone verification**) is needed only for GPU or
   internet in notebooks. **This notebook needs neither**, so you can skip it.

### 3.2 Download the notebook file from GitHub

1. Sign in to GitHub with an account that can see the private repo.
2. Open `https://github.com/NoboIshraque/SME-financing-copilot/blob/main/ml/notebooks/01_forecast_backtest.ipynb`
   (or click through: repo → `ml` → `notebooks` → `01_forecast_backtest.ipynb`).
3. Top right of the file view, click the **Download raw file** button (arrow pointing down).
   The file lands in your Downloads folder. Check that the name ends in `.ipynb`, not `.txt`.

### 3.3 Create the notebook on Kaggle

1. Kaggle → left menu **Create** (the **+** button) → **New Notebook**.
2. In the notebook editor: menu **File** → **Import Notebook** → choose
   `01_forecast_backtest.ipynb` → **Import**. The cells replace the empty notebook.
3. Right panel → **Session options** (or **Settings**): Accelerator **None** (CPU). Internet
   can stay **off**.

### 3.4 Attach the dataset

1. Right panel → **Input** → **+ Add Input** (older layout: **Add Data**).
2. Search: `online retail ii uci`
3. Pick the dataset by **mashlyn**: `mashlyn/online-retail-ii-uci` → click **+** / **Add**.
4. It appears under Input as `/kaggle/input/online-retail-ii-uci/…`. The notebook finds the
   file `online_retail_II.csv` (or `.xlsx`) anywhere under `/kaggle/input` by itself.

### 3.5 Run

1. Menu **Run** → **Run all** (or the **Run All** button at the top).
2. Time: about **5–10 minutes** on CPU (the notebook's own estimate).
3. Progress: the first code cell prints the number of rows and days; the walk-forward cell
   prints one line per origin, like `2011-03-01 done`, about 19 lines.
4. **Finished** when: every code cell shows a number in `[ ]`, no cell shows `[*]`, and the
   last cell has printed a block of JSON starting with `{"dataset": "UCI Online Retail II …`.
5. Recommended: **Save Version** (top right) → **Save & Run All (Commit)** → **Save**. Kaggle
   reruns it in the background and keeps the outputs permanently.

### 3.6 Download the results

Exact output path (from the code): `/kaggle/working/hishab_ml/`.

1. Right panel → **Output** (or the version's **Output** tab) → `/kaggle/working` →
   `hishab_ml`.
2. Download these **two** files (hover → **⋮** → **Download**):
   - `forecast_backtest.json`
   - `forecast_backtest_origins.csv`
3. **Do not** upload `forecast_backtest_ckpt.pkl` (a resume checkpoint, not a result).

### 3.7 What "good" looks like (a 1-minute glance)

Open `forecast_backtest.json` in Notepad:

- `"data_mode": "public"` ✔ (the repo test requires exactly this).
- `"period": ["2009-12-01", "2011-12-09"]` or close to it.
- `"chosen_model"` is one of `seasonal_naive`, `ets`, `lightgbm_quantile`.
- Under `"models"`, each model has `"origins"` around 19 and `"coverage_80_mean"` between 0 and
  1 (near 0.8 is a well-calibrated band).
- Under `"gaps"`, `gap_hit_rate` and `mean_lead_time_days` have numbers (a `null` simply means
  no real gaps or no hits for that cushion; that is a result too).

Do not "fix" numbers you do not like. They go in as they are.

### 3.8 Put the files in the repo

The repo test `backend/tests/ml/test_artifacts.py` reads `ml/artifacts/forecast_backtest.json`
(it checks `data_mode == "public"`, that `chosen_model` is one of the models, and every
`coverage_80_mean` is between 0 and 1). Both files go into **`ml/artifacts/`**.

**Via the GitHub website (no git needed):**

1. Open `https://github.com/NoboIshraque/SME-financing-copilot/tree/main/ml/artifacts`.
2. **Add file** → **Upload files**.
3. Drag in `forecast_backtest.json` and `forecast_backtest_origins.csv`.
4. Commit message: `WP-17: notebook 01 results on UCI Online Retail II (real public data)`.
5. Choose **Create a new branch for this commit and start a pull request**. Branch name:
   `wp-17-notebook01`.
6. **Propose changes** → **Create pull request**.
7. Post in the group: "Notebook 01 PR ready". The on-duty orchestrator reviews, ticks WP-17
   milestone 1, updates `docs/PLAN.md` §8 and merges.

**Or** send the two files to the orchestrator session (attach them) and ask it to commit them.

### 3.9 Troubleshooting

| Problem | Fix |
| --- | --- |
| `FileNotFoundError` / tries to download from UCI and fails with no internet | The dataset is not attached. Do 3.4 again, then **Run all**. If the file has a different name, put its path in the `DATA_PATH = os.environ.get("HISHAB_RETAIL_PATH", "")` line, e.g. `DATA_PATH = "/kaggle/input/online-retail-ii-uci/online_retail_II.csv"` |
| `KeyError: 'Price'` or `'InvoiceDate'` | A different dataset was attached. Remove it and add `mashlyn/online-retail-ii-uci` |
| The session restarted or timed out | Just **Run all** again. The walk-forward resumes from `forecast_backtest_ckpt.pkl` (it saves after every origin) |
| `ModuleNotFoundError: lightgbm` or `statsmodels` | Rare on Kaggle (both are pre-installed). Add a cell at the top with `!pip install lightgbm statsmodels`; this needs **Internet on**, which needs phone verification. Or use Part 2 |
| `pip` errors about versions | Ignore warnings; only a red error that stops a cell matters. Screenshot it and post it; do not change the code |
| Takes longer than 30 minutes | Check Accelerator is **None** and the session is still running (top right). Kaggle CPU is sometimes slow; let it finish |

---

## Part 4. HANDME prompt for another chat with internet access

Paste everything in the box into a **fresh** Claude Code chat that has access to the repo and
unrestricted network.

```text
You are a helper on the DecisionGuard hackathon repo (FinTechathon 2026 Topic E). Task: run
notebook 01 (real-data cash-forecast backtest) and commit its results. Deadline today
20 Oct 2026 21:59 Dhaka.

1. Get the repo: attach/clone NoboIshraque/SME-financing-copilot (private). Read CLAUDE.md
   first and follow it. Never read or print any .env file. Do not edit files outside the
   ones listed below.
2. git fetch && git switch main && git pull, then git switch -c wp-17-notebook01.
3. Read ml/notebooks/01_forecast_backtest.py (the source of truth; the .ipynb is generated
   from it), ml/README.md, docs/packages/WP-17.md and backend/tests/ml/test_artifacts.py.
4. Run the script in a scratch directory outside the repo (it downloads
   https://archive.ics.uci.edu/static/public/502/online+retail+ii.zip into the current
   directory and writes outputs to $HISHAB_OUT):
     mkdir -p /tmp/nb01 && cd /tmp/nb01
     HISHAB_OUT=/tmp/nb01/out uv run --no-project --python 3.12 \
       --with pandas --with numpy --with lightgbm --with statsmodels --with openpyxl \
       python <repo>/ml/notebooks/01_forecast_backtest.py
   (openpyxl is needed because the UCI zip holds an .xlsx file.) Expect several minutes.
   If the download is blocked, stop and report it; do not substitute another dataset.
5. Copy exactly two files into the repo: /tmp/nb01/out/forecast_backtest.json ->
   ml/artifacts/forecast_backtest.json and /tmp/nb01/out/forecast_backtest_origins.csv ->
   ml/artifacts/forecast_backtest_origins.csv. Do not copy forecast_backtest_ckpt.pkl or
   the dataset. Do not edit any number in them.
6. Tests: cd backend && uv run pytest tests/ml -q (test_forecast_backtest_report_is_well_formed_when_present
   must now run, not skip), then from the repo root npm run test:backend and npm run evidence.
7. Update docs/packages/WP-17.md STATUS: tick "1 Forecast backtest" and add one line with the
   chosen model, its coverage_80_mean, and the gap hit rate, false alarm rate and lead time
   for the 1-day cushion, copied from the JSON. Update the WP-17 row in docs/PLAN.md section 8
   the same way. Label the data "real public data (UCI Online Retail II, CC BY 4.0)", never
   "synthetic" and never "our shops".
8. Do not edit docs/submission/ (owned by WP-19). In the PR description, note that
   docs/submission/technical-documentation.md §3.3 still says the real-data backtest "has not
   produced results yet", and quote the numbers for the orchestrator.
9. Commit with messages in the style "WP-17: notebook 01 results on UCI Online Retail II",
   push the branch wp-17-notebook01, open a pull request to main. Never merge, never push to
   main. Do not fabricate or change numbers: every number you write is copied exactly
   from the files the script wrote. Report the PR link and the key numbers.

Stretch goal, only if all of the above is done and there is time: docs/packages/WP-20.md lists
optional real public datasets: "Bangladeshi retailer daily sales 2013-2017" (Mendeley DOI
10.17632/xwmbk7n3c8.1) and "Comprehensive Retail Network Dataset of Bangladesh" (Mendeley DOI
10.17632/mgzvngzng2.1), hosted on data.mendeley.com (downloads may redirect to another host;
allow the host the error names). No notebook reads them yet. Do not start this without asking
the user first; check each licence on download.
```

Network hosts that chat needs: `archive.ics.uci.edu` (dataset), the Python package index (for
`uv`), and `github.com` (clone, push, PR). The stretch goal also needs `data.mendeley.com`.
