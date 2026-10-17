# ---
# jupyter:
#   kernelspec:
#     display_name: Python 3
#     name: python3
# ---

# %% [markdown]
# # 02 — Payment-delay model (Hishab WP-17, feeds WP-05 receivables risk and WP-04 collections)
#
# Predicts **days late** for each credit sale (baki invoice) from information available on
# the day the invoice is issued, and the probability it is paid more than 7 days late.
#
# **Data:** the synthetic SME universe in this repo (`data/synthetic/universe/*/baki_register.csv`,
# labelled synthetic) plus, when present, consenting shops' anonymised ledgers
# (`data/real_anonymised/*/baki_register.csv`, WP-20). Results say which data they come from.
#
# **No leakage:** every feature uses only invoices *paid before* the new invoice's issue date;
# train / test split is by time (test = invoices issued in the last 4 months).
#
# Runs on CPU in about a minute. Run from the repo root (`ml/notebooks/`), or on Kaggle after
# uploading `data/` as a dataset and setting `HISHAB_DATA`.

# %%
import json
import os
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
import yaml
from sklearn.metrics import mean_absolute_error, roc_auc_score

SEED = 20261020
here = Path.cwd()
REPO = next((p for p in [here, *here.parents] if (p / "data" / "synthetic").exists()), here)
DATA = Path(os.environ.get("HISHAB_DATA", REPO / "data"))
OUT = Path(os.environ.get("HISHAB_OUT", REPO / "ml" / "artifacts"))
OUT.mkdir(parents=True, exist_ok=True)
LATE_DAYS = 7
SPLIT = pd.Timestamp("2026-05-01")  # test: issued on or after this date

# %% [markdown]
# ## 1. Load invoices

# %%
frames = []
for source, pattern in (("synthetic", "synthetic/universe/*/baki_register.csv"),
                        ("real_anonymised", "real_anonymised/*/baki_register.csv")):
    for path in sorted(DATA.glob(pattern)):
        df = pd.read_csv(path, parse_dates=["issue_date", "due_date", "paid_date"])
        df["sme"] = path.parent.name
        df["source"] = source
        frames.append(df)
inv = pd.concat(frames, ignore_index=True)
inv = inv[~inv["number"].str.startswith("RING-")]  # mesh demo debts are not customer habits
sectors = {}
for sme in inv["sme"].unique():
    profile = DATA / "synthetic" / "universe" / sme / "profile.json"
    sectors[sme] = json.loads(profile.read_text())["sector"] if profile.exists() else "unknown"
inv["sector"] = inv["sme"].map(sectors)
festivals = yaml.safe_load((DATA / "public/calendar/bd_festivals.yaml").read_text())["festivals"]
eids = pd.to_datetime([f["date"] for f in festivals if f["name"].startswith("eid")]).sort_values()
print(inv.groupby(["source", "status"]).size())

# %% [markdown]
# ## 2. Features known on the issue date

# %%
inv = inv.sort_values(["issue_date", "number"]).reset_index(drop=True)
inv["days_late"] = (inv["paid_date"] - inv["due_date"]).dt.days
inv["customer"] = inv["sme"] + "|" + inv["party"]


def days_to_next_eid(day: pd.Timestamp) -> int:
    later = eids[eids >= day]
    return int((later[0] - day).days) if len(later) else 365


rows = []
for i, row in inv.iterrows():
    past = inv[(inv["customer"] == row["customer"]) & (inv["paid_date"] < row["issue_date"])]
    rows.append({
        "hist_n": len(past),
        "hist_mean_late": past["days_late"].mean() if len(past) else np.nan,
        "hist_median_late": past["days_late"].median() if len(past) else np.nan,
        "hist_std_late": past["days_late"].std() if len(past) > 1 else np.nan,
        "hist_share_late7": (past["days_late"] > LATE_DAYS).mean() if len(past) else np.nan,
        "amount_ratio": row["amount"] / past["amount"].median() if len(past) else np.nan,
        "log_amount": np.log1p(row["amount"]),
        "terms_days": (row["due_date"] - row["issue_date"]).days,
        "due_weekday": row["due_date"].dayofweek,
        "days_due_to_eid": days_to_next_eid(row["due_date"]),
        "sector": row["sector"],
    })
X_all = pd.DataFrame(rows, index=inv.index)
X_all["sector"] = X_all["sector"].astype("category")
labelled = inv["status"].eq("paid")  # disputed and open invoices have no outcome yet
X, y = X_all[labelled], inv.loc[labelled, "days_late"]
is_test = inv.loc[labelled, "issue_date"] >= SPLIT
X_train, X_test, y_train, y_test = X[~is_test], X[is_test], y[~is_test], y[is_test]
print(f"train {len(X_train)}  test {len(X_test)}")

# %% [markdown]
# ## 3. Models: customer-history baseline vs LightGBM

# %%
baseline = X_test["hist_mean_late"].fillna(y_train.mean())
reg = lgb.LGBMRegressor(objective="l1", n_estimators=400, learning_rate=0.03, num_leaves=15,
                        min_child_samples=20, random_state=SEED, verbose=-1)
reg.fit(X_train, y_train)
pred = reg.predict(X_test)
clf = lgb.LGBMClassifier(n_estimators=300, learning_rate=0.03, num_leaves=15,
                         min_child_samples=20, random_state=SEED, verbose=-1)
clf.fit(X_train, (y_train > LATE_DAYS).astype(int))
p_late = clf.predict_proba(X_test)[:, 1]
y_late = (y_test > LATE_DAYS).astype(int)

metrics = {
    "data": sorted(inv.loc[labelled, "source"].unique().tolist()),
    "data_mode": "synthetic" if set(inv["source"]) == {"synthetic"} else "mixed",
    "train_rows": int(len(X_train)), "test_rows": int(len(X_test)),
    "split": f"time: test = issued on/after {SPLIT.date()}",
    "mae_days": {"customer_mean_baseline": round(mean_absolute_error(y_test, baseline), 3),
                 "lightgbm": round(mean_absolute_error(y_test, pred), 3)},
    "late_over_7_days": {
        "share_in_test": round(float(y_late.mean()), 4),
        "auc_lightgbm": round(float(roc_auc_score(y_late, p_late)), 4) if y_late.nunique() > 1
        else None,
        "auc_history_share": round(float(roc_auc_score(
            y_late, X_test["hist_share_late7"].fillna(0))), 4) if y_late.nunique() > 1 else None,
    },
    "feature_importance": dict(sorted(zip(X.columns, map(int, reg.feature_importances_)),
                                      key=lambda kv: -kv[1])),
    "seed": SEED,
}
# Prefer the simplest model that is not clearly worse: LightGBM must beat the customer-history
# baseline by at least 5% MAE to be used by WP-05.
gain = 1 - metrics["mae_days"]["lightgbm"] / metrics["mae_days"]["customer_mean_baseline"]
metrics["decision"] = {
    "use": "lightgbm" if gain >= 0.05 else "customer_history_baseline",
    "mae_improvement": round(gain, 4),
    "rule": "use LightGBM only if it cuts MAE by >= 5% versus the customer-history baseline",
}
print(json.dumps(metrics, indent=2))

# %% [markdown]
# ## 4. Export (small text models; WP-05 loads them with `lightgbm.Booster(model_file=...)`)

# %%
reg.booster_.save_model(str(OUT / "payment_delay_days.txt"))
clf.booster_.save_model(str(OUT / "payment_late7_prob.txt"))
schema = {"features": list(X.columns), "categorical": {"sector": list(X["sector"].cat.categories)},
          "target_days": "paid_date - due_date", "late_threshold_days": LATE_DAYS}
(OUT / "payment_delay_schema.json").write_text(json.dumps(schema, indent=2))
(OUT / "payment_delay_metrics.json").write_text(json.dumps(metrics, indent=2))
fixture = X_test.head(5).copy()
fixture["sector"] = fixture["sector"].astype(str)
fixture["expected_days_late"] = np.round(reg.predict(X_test.head(5)), 6)
fixture.to_json(OUT / "payment_delay_fixture.json", orient="records", indent=2)
print("saved to", OUT)
