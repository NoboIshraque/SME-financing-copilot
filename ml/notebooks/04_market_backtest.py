# ---
# jupyter:
#   kernelspec:
#     display_name: Python 3
#     name: python3
# ---

# %% [markdown]
# # 04 — Price-alert backtest on real Dhaka market prices (Hishab WP-17 → WP-09; FEATURES N3)
#
# WP-09 alerts a shop when an input it buys moves more than a threshold above its 4-week
# median. Does that rule fire **before** big price spikes, and how often does it cry wolf?
#
# **Data:** *AgriPriceBD* (Mendeley Data, DOI 10.17632/bkmxnrn3hn.1, published 27 Mar 2026):
# daily wholesale and retail min/max prices (Tk/kg) for garlic, chickpea, green chilli,
# cucumber and sweet pumpkin over about five years, digitised from government market reports.
# Four green-chilli days in January 2024 are zero (portal outage) and are dropped here.
#
# **How to run:** download the dataset files from the DOI page → Kaggle *Add data → Upload*
# (or set `HISHAB_PRICES` to a folder) → *Run all* (CPU, < 2 min). Download
# `hishab_ml/market_alert_backtest.json` → `ml/artifacts/`.

# %%
import glob
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd

SRC = os.environ.get("HISHAB_PRICES", "/kaggle/input")
OUT = Path(os.environ.get("HISHAB_OUT", "/kaggle/working/hishab_ml" if Path("/kaggle").exists()
                          else "hishab_ml"))
OUT.mkdir(parents=True, exist_ok=True)
WINDOW = 28  # days in the trailing median (the WP-09 rule)
THRESHOLDS = (0.05, 0.08, 0.12, 0.15)
SPIKE = 0.25  # a "big move": price ends up >= 25% above its trailing median
LOOKBACK_ALERT = 21  # an alert counts as early warning if it fired within 21 days before a spike
CONFIRM = 0.10  # an alert is "right" if the price rises another 10% within 21 days


# %% [markdown]
# ## 1. Load (column names are matched loosely so CSV or Excel exports both work)

# %%
def load_prices(src: str) -> pd.DataFrame:
    files = [f for f in glob.glob(f"{src}/**/*", recursive=True)
             if f.lower().endswith((".csv", ".xlsx", ".xls"))]
    frames = []
    for f in files:
        df = pd.read_csv(f) if f.lower().endswith(".csv") else pd.read_excel(f)
        cols = {c: c.strip().lower().replace(" ", "_") for c in df.columns}
        df = df.rename(columns=cols)
        need = {"date", "retail_price_minimum", "retail_price_maximum"}
        alias = {"retail_min": "retail_price_minimum", "retail_max": "retail_price_maximum",
                 "product_name": "product", "commodity": "product", "product": "product"}
        df = df.rename(columns={k: v for k, v in alias.items() if k in df.columns})
        if not need <= set(df.columns):
            continue
        if "product" not in df.columns:
            df["product"] = Path(f).stem
        frames.append(df)
    if not frames:
        raise FileNotFoundError(f"no AgriPriceBD files with retail min/max columns under {src}")
    df = pd.concat(frames, ignore_index=True)
    df["date"] = pd.to_datetime(df["date"])
    df["mid"] = (df["retail_price_minimum"] + df["retail_price_maximum"]) / 2
    df = df[df["mid"] > 0]  # drop the documented zero-price outage days
    return df.groupby(["product", "date"], as_index=False)["mid"].mean()


prices = load_prices(SRC)
print(prices.groupby("product")["date"].agg(["min", "max", "count"]))


# %% [markdown]
# ## 2. Alerts vs spikes, per commodity and threshold

# %%
def evaluate(series: pd.Series, threshold: float) -> dict:
    series = series.asfreq("D").interpolate(limit=3).dropna()
    median = series.rolling(WINDOW, min_periods=WINDOW // 2).median().shift(1)
    move = series / median - 1
    alerts = move.index[move >= threshold]
    spike_days = move.index[move >= SPIKE]
    episodes = [d for i, d in enumerate(spike_days)
                if i == 0 or (d - spike_days[i - 1]).days > WINDOW]  # first day of each spike
    caught, leads = 0, []
    for start in episodes:
        before = alerts[(alerts < start) & (alerts >= start - pd.Timedelta(days=LOOKBACK_ALERT))]
        if len(before):
            caught += 1
            leads.append((start - before[0]).days)
    right = 0
    alert_starts = [d for i, d in enumerate(alerts) if i == 0 or (d - alerts[i - 1]).days > 7]
    for d in alert_starts:
        future = series[d: d + pd.Timedelta(days=LOOKBACK_ALERT)]
        if len(future) and future.max() >= series[d] * (1 + CONFIRM):
            right += 1
    return {
        "spikes": len(episodes),
        "spikes_warned": caught,
        "warning_rate": round(caught / len(episodes), 4) if episodes else None,
        "median_lead_days": float(np.median(leads)) if leads else None,
        "alert_episodes": len(alert_starts),
        "alert_precision": round(right / len(alert_starts), 4) if alert_starts else None,
    }


results = {}
for product, g in prices.groupby("product"):
    series = g.set_index("date")["mid"].sort_index()
    results[product] = {f"{t:.2f}": evaluate(series, t) for t in THRESHOLDS}


def overall(threshold: str) -> dict:
    rows = [results[p][threshold] for p in results]
    spikes = sum(r["spikes"] for r in rows)
    warned = sum(r["spikes_warned"] for r in rows)
    precisions = [r["alert_precision"] for r in rows if r["alert_precision"] is not None]
    return {"spikes": spikes, "warning_rate": round(warned / spikes, 4) if spikes else None,
            "mean_alert_precision": round(float(np.mean(precisions)), 4) if precisions else None}


summary = {t: overall(f"{t:.2f}") for t in THRESHOLDS}
# Recommend the threshold with the best balance (harmonic mean of warning rate and precision).
def balance(s):
    w, p = s["warning_rate"] or 0, s["mean_alert_precision"] or 0
    return 0 if w + p == 0 else 2 * w * p / (w + p)


recommended = max(THRESHOLDS, key=lambda t: balance(summary[t]))
report = {
    "dataset": "AgriPriceBD (Mendeley Data, DOI 10.17632/bkmxnrn3hn.1), retail mid price",
    "data_mode": "public",
    "rule": f"alert when price >= threshold above the trailing {WINDOW}-day median",
    "spike_definition": f"price >= {int(SPIKE * 100)}% above the trailing median",
    "early_warning_window_days": LOOKBACK_ALERT,
    "alert_correct_if": f"price rises another {int(CONFIRM * 100)}% within {LOOKBACK_ALERT} days",
    "by_threshold": {f"{t:.2f}": summary[t] for t in THRESHOLDS},
    "by_product": results,
    "recommended_threshold": recommended,
}
(OUT / "market_alert_backtest.json").write_text(json.dumps(report, indent=2))
print(json.dumps(report["by_threshold"], indent=2), "\nrecommended:", recommended)
