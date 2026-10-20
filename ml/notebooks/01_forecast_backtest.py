# ---
# jupyter:
#   kernelspec:
#     display_name: Python 3
#     name: python3
# ---

# %% [markdown]
# # 01 — Cash-forecast backtest on real retail data (Hishab WP-17, FEATURES N15)
#
# **Question:** does a forecaster like Hishab's flag cash gaps *before* they happen, on data
# we did not generate? We use the UCI **Online Retail II** dataset (real transactions of a UK
# online retailer, Dec 2009 – Dec 2011, CC BY 4.0) as a stand-in for a small firm's daily
# inflows, then walk forward through 2011 with **no leakage** (every forecast uses only data
# before its origin).
#
# **How to run (Kaggle, CPU is enough, ~5–10 min):**
# 1. New notebook → *File → Import notebook* → this `.ipynb`.
# 2. *Add data* → search **"online retail ii uci"** → add `mashlyn/online-retail-ii-uci`.
# 3. *Run all*. Results are checkpointed after every forecast origin in `/kaggle/working`,
#    so a restart resumes where it stopped.
# 4. Download `/kaggle/working/hishab_ml/forecast_backtest.json` and `forecast_backtest_origins.csv`
#    → commit them to `ml/artifacts/` in the repo (or post them in the group).
#
# Colab: upload the dataset CSV and set `DATA_PATH` below, or let the cell download it from UCI.

# %%
import glob
import json
import os
import pickle
import warnings
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from statsmodels.tsa.holtwinters import ExponentialSmoothing

warnings.filterwarnings("ignore")
SEED = 20261020
np.random.seed(SEED)

DATA_PATH = os.environ.get("HISHAB_RETAIL_PATH", "")  # set to override discovery
# Optional second dataset: a two-column daily series (date, value), e.g. the Bangladeshi
# retailer's daily sales 2013-2017 (Mendeley 10.17632/xwmbk7n3c8.1, CC BY 4.0, copy in
# data/public/retail_bd/). Its outputs are named forecast_backtest_bd.*.
DAILY_PATH = os.environ.get("HISHAB_DAILY_PATH", "")
STEM = "forecast_backtest_bd" if DAILY_PATH else "forecast_backtest"
OUT = Path(os.environ.get("HISHAB_OUT", "/kaggle/working/hishab_ml" if Path("/kaggle").exists()
                          else "hishab_ml"))
OUT.mkdir(parents=True, exist_ok=True)
HORIZON = 28  # days forecast from each origin
STEP = 14  # days between origins
QUANTILES = (0.1, 0.5, 0.9)
OUTFLOW_RATIO = 0.95  # weekly supplier payments as a share of trailing average inflow
# Cushion = how many days of average sales the opening balance sits above the expected low
# point. Tested at three levels (tight / medium / comfortable).
CUSHIONS = (0.5, 1.0, 2.0)


# %% [markdown]
# ## 1. Load and clean
# Net cash in per day = sum(Quantity × Price) over all invoices, cancellations (invoices
# starting with "C") included as negative. Days with no trading are 0.

# %%
def find_data() -> str:
    if DATA_PATH:
        return DATA_PATH
    hits = sorted(glob.glob("/kaggle/input/**/online_retail_II.csv", recursive=True)
                  + glob.glob("/kaggle/input/**/online_retail_II.xlsx", recursive=True))
    if hits:
        return hits[0]
    local = Path("online_retail_II.xlsx")
    if not local.exists():  # Colab fallback: official UCI archive
        import urllib.request
        import zipfile
        url = "https://archive.ics.uci.edu/static/public/502/online+retail+ii.zip"
        urllib.request.urlretrieve(url, "online_retail_ii.zip")
        zipfile.ZipFile("online_retail_ii.zip").extractall(".")
    return str(local)


def load(path: str) -> pd.DataFrame:
    if path.endswith(".csv"):
        df = pd.read_csv(path, encoding="ISO-8859-1")
    else:
        sheets = pd.read_excel(path, sheet_name=None)
        df = pd.concat(sheets.values(), ignore_index=True)
    df = df.rename(columns={"Customer ID": "CustomerID", "UnitPrice": "Price"})
    df["InvoiceDate"] = pd.to_datetime(df["InvoiceDate"])
    df["amount"] = df["Quantity"] * df["Price"]
    return df


def load_daily(path: str) -> pd.Series:
    table = pd.read_csv(path) if path.endswith(".csv") else pd.read_excel(path)
    table = table.loc[:, ~table.columns.astype(str).str.startswith("Unnamed")]  # a row-number column
    days, values = pd.to_datetime(table.iloc[:, 0]).dt.normalize(), table.iloc[:, 1].astype(float)
    return values.groupby(days).sum()


if DAILY_PATH:
    raw = None
    daily = load_daily(DAILY_PATH)
else:
    raw = load(find_data())
    daily = raw.groupby(raw["InvoiceDate"].dt.normalize())["amount"].sum()
daily = daily.reindex(pd.date_range(daily.index.min(), daily.index.max(), freq="D"), fill_value=0)
daily.name = "cash_in"
print(f"{len(raw) if raw is not None else len(daily):,} rows -> {len(daily)} days, {daily.index.min().date()} .. {daily.index.max().date()}")
print(daily.describe().round(0))


# %% [markdown]
# ## 2. Three forecasters (each returns P10 / P50 / P90 per day)
# - **Seasonal naive:** the same weekday last week; bands from the last 8 weeks' errors.
# - **ETS:** Holt-Winters, additive damped trend + weekly seasonality; bands from residuals.
# - **LightGBM quantile:** calendar features + lags of at least 28 days (so the whole 28-day
#   horizon is forecast directly from known data, no recursion and no leakage).

# %%
def residual_bands(history: pd.Series, fitted: pd.Series, p50: np.ndarray):
    err = (history - fitted).dropna().iloc[-56:]
    lo, hi = np.quantile(err, 0.1), np.quantile(err, 0.9)
    return np.maximum(p50 + lo, 0), p50, p50 + hi


def seasonal_naive(history: pd.Series, horizon: int):
    p50 = np.array([history.iloc[-7 + (h % 7)] for h in range(horizon)])
    fitted = history.shift(7)
    return residual_bands(history, fitted, p50)


def ets(history: pd.Series, horizon: int):
    model = ExponentialSmoothing(history.clip(lower=0) + 1.0, trend="add", damped_trend=True,
                                 seasonal="add", seasonal_periods=7).fit(optimized=True)
    p50 = np.maximum(model.forecast(horizon).to_numpy() - 1.0, 0)
    return residual_bands(history, model.fittedvalues - 1.0, p50)


def features(index: pd.DatetimeIndex, series: pd.Series) -> pd.DataFrame:
    f = pd.DataFrame(index=index)
    f["dow"] = index.dayofweek
    f["dom"] = index.day
    f["month"] = index.month
    f["woy"] = index.isocalendar().week.astype(int).to_numpy()
    xmas = pd.to_datetime([f"{y}-12-25" for y in index.year])
    f["days_to_xmas"] = (xmas - index).days
    full = series.reindex(series.index.union(index))
    for lag in (28, 35, 42, 56, 364):
        f[f"lag{lag}"] = full.shift(lag).reindex(index).to_numpy()
    f["roll28_at_lag28"] = full.shift(28).rolling(28).mean().reindex(index).to_numpy()
    return f


def lgbm(history: pd.Series, horizon: int):
    train_idx = history.index[400:] if len(history) > 450 else history.index[60:]
    x_train = features(train_idx, history)
    y_train = history.reindex(train_idx)
    future = pd.date_range(history.index[-1] + pd.Timedelta(days=1), periods=horizon, freq="D")
    x_future = features(future, history)
    out = []
    for q in QUANTILES:
        model = lgb.LGBMRegressor(objective="quantile", alpha=q, n_estimators=300,
                                  learning_rate=0.05, num_leaves=15, min_child_samples=10,
                                  random_state=SEED, verbose=-1)
        model.fit(x_train, y_train)
        out.append(model.predict(x_future))
    p10, p50, p90 = np.sort(np.vstack(out), axis=0)  # enforce p10 <= p50 <= p90
    return np.maximum(p10, 0), p50, p90


MODELS = {"seasonal_naive": seasonal_naive, "ets": ets, "lightgbm_quantile": lgbm}


# %% [markdown]
# ## 3. Cash-gap definition (same rule for actuals and forecasts)
# Real inflows are combined with a fixed, simple outflow schedule a small shop could have:
# weekly supplier payments of 95% of the trailing-90-day average inflow (Mondays) plus rent of
# 4 days' average inflow on the 1st. The buffer is 3 days of average inflow. The opening balance
# is set so that, if sales were exactly average, the lowest balance would sit a *cushion* of
# 0.5, 1 or 2 days of sales above the buffer. A **gap** is a day the real balance falls below the
# buffer. The forecast **flags** a gap if its worst-case (10%) cumulative path crosses it. That
# path is the cumulative P50 minus 1.2816 x the cumulative spread (daily spread =
# (P90 - P10) / 2.5631, days independent): summing daily P10s would be far too pessimistic.

# %%
def outflows(index: pd.DatetimeIndex, avg: float) -> np.ndarray:
    pay = np.where(index.dayofweek == 0, OUTFLOW_RATIO * avg * 7, 0.0)
    rent = np.where(index.day == 1, 4 * avg, 0.0)
    return pay + rent


def first_breach_path(path: np.ndarray, buffer: float):
    hits = np.nonzero(path < buffer)[0]
    return int(hits[0]) if len(hits) else None


def worst_case_cumulative(p10: np.ndarray, p50: np.ndarray, p90: np.ndarray) -> np.ndarray:
    sd = (p90 - p10) / 2.5631
    return np.cumsum(p50) - 1.2816 * np.sqrt(np.cumsum(sd ** 2))


# %% [markdown]
# ## 4. Walk forward (checkpointed after every origin)

# %%
ckpt = OUT / f"{STEM}_ckpt.pkl"
results = pickle.loads(ckpt.read_bytes()) if ckpt.exists() else []
done = {(r["origin"], r["model"]) for r in results}
first_origin = daily.index[0] + pd.Timedelta(days=365) if DAILY_PATH else "2011-03-01"
origins = pd.date_range(first_origin, daily.index[-1] - pd.Timedelta(days=HORIZON), freq=f"{STEP}D")
print(f"{len(origins)} origins x {len(MODELS)} models; {len(done)} already done")

for origin in origins:
    history = daily[daily.index < origin]
    actual = daily[(daily.index >= origin)][:HORIZON].to_numpy()
    index = pd.date_range(origin, periods=HORIZON, freq="D")
    avg = float(history.iloc[-90:].mean())
    out = outflows(index, avg)
    buffer = 3 * avg
    expected_low = float(np.min(np.cumsum(np.full(HORIZON, avg) - out)))
    for name, fn in MODELS.items():
        if (str(origin.date()), name) in done:
            continue
        p10, p50, p90 = fn(history, HORIZON)
        gaps = {}
        worst = worst_case_cumulative(p10, p50, p90)
        for cushion in CUSHIONS:
            opening = buffer - expected_low + cushion * avg
            real_path = opening + np.cumsum(actual - out)
            flag_path = opening + worst - np.cumsum(out)
            gaps[f"true_gap_day_{cushion}"] = first_breach_path(real_path, buffer)
            gaps[f"flag_day_{cushion}"] = first_breach_path(flag_path, buffer)
        weekly_true = actual.reshape(4, 7).sum(axis=1)
        weekly_pred = p50.reshape(4, 7).sum(axis=1)
        mask = weekly_true > 0
        results.append({
            "origin": str(origin.date()), "model": name,
            "wape": float(np.abs(actual - p50).sum() / max(np.abs(actual).sum(), 1e-9)),
            "weekly_mape": float(np.mean(np.abs(weekly_true[mask] - weekly_pred[mask])
                                         / weekly_true[mask])) if mask.any() else None,
            "coverage_80": float(np.mean((actual >= p10) & (actual <= p90))),
            "pinball": float(np.mean([np.mean(np.maximum(q * (actual - p), (q - 1) * (actual - p)))
                                      for q, p in zip(QUANTILES, (p10, p50, p90), strict=True)])),
            **gaps,
        })
        ckpt.write_bytes(pickle.dumps(results))
    print(origin.date(), "done")


# %% [markdown]
# ## 5. Results
# Gap metrics: **hit rate** = share of real gaps the model flagged in advance (flag day ≤ gap
# day); **false alarm rate** = share of gap-free windows the model flagged; **lead time** =
# days between the origin (when the forecast is made) and the real gap, for hits.

# %%
df = pd.DataFrame(results)
summary = {}
for name, g in df.groupby("model"):
    gap_metrics = {}
    for cushion in CUSHIONS:
        t, f = f"true_gap_day_{cushion}", f"flag_day_{cushion}"
        gaps, calm = g[g[t].notna()], g[g[t].isna()]
        hits = gaps[gaps[f].notna() & (gaps[f] <= gaps[t])]
        gap_metrics[f"cushion_{cushion}_days"] = {
            "real_gaps": int(len(gaps)),
            "gap_hit_rate": round(len(hits) / len(gaps), 4) if len(gaps) else None,
            "false_alarm_rate": round(float(calm[f].notna().mean()), 4) if len(calm) else None,
            "mean_lead_time_days": round(float(hits[t].mean()), 2) if len(hits) else None,
        }
    summary[name] = {
        "origins": int(len(g)),
        "wape_mean": round(float(g["wape"].mean()), 4),
        "weekly_mape_mean": round(float(g["weekly_mape"].dropna().mean()), 4),
        "coverage_80_mean": round(float(g["coverage_80"].mean()), 4),
        "pinball_mean": round(float(g["pinball"].mean()), 2),
        "gaps": gap_metrics,
    }
best = min(summary, key=lambda m: summary[m]["pinball_mean"])
report = {
    "dataset": ("Bangladeshi retailer daily sales 2013-2017 (Mendeley 10.17632/xwmbk7n3c8.1, "
                "CC BY 4.0), units sold per day as a stand-in for daily inflow" if DAILY_PATH
                else "UCI Online Retail II (CC BY 4.0), daily net cash-in"),
    "data_mode": "public",
    "period": [str(daily.index.min().date()), str(daily.index.max().date())],
    "horizon_days": HORIZON, "origin_step_days": STEP, "seed": SEED,
    "no_leakage": "each forecast uses only data before its origin; LightGBM lags >= 28 days",
    "gap_rule": "balance < 3 days of average inflow; outflows: weekly supplier run at 95% of "
                "average inflow + rent of 4 days on the 1st; opening = cushion of 0.5/1/2 days "
                "above the expected low point",
    "models": summary, "chosen_model": best,
}
(OUT / f"{STEM}.json").write_text(json.dumps(report, indent=2))
df.to_csv(OUT / f"{STEM}_origins.csv", index=False)
print(json.dumps(report, indent=2))
