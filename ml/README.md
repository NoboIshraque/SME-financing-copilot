# ML notebooks (WP-17)

Source of truth: the `.py` files (jupytext percent format); the `.ipynb` files are generated
with `jupytext --to ipynb`. Outputs land in `ml/artifacts/` (small files only; checkpoints and
large models stay out of git).

| Notebook | Runs on | Data | Output |
| --- | --- | --- | --- |
| `01_forecast_backtest` | Kaggle CPU (Labib) | UCI Online Retail II (real, CC BY 4.0) | `forecast_backtest.json`, per-origin CSV |
| `02_payment_delay` | anywhere, ~1 min | synthetic universe (+ WP-20 real anonymised when present) | LightGBM text models, metrics, schema, fixture |
| `03_injection_classifier` | Kaggle GPU | public injection sets + EN/BN/Banglish/ZH paraphrases | ONNX model, per-language metrics |
| `04_market_backtest` | Kaggle CPU | public Dhaka price series | alert lead-time metrics |

Local run: `uv venv ml/.venv && uv pip install --python ml/.venv pandas numpy lightgbm statsmodels scikit-learn pyyaml jupytext nbconvert ipykernel`,
then `ml/.venv/bin/jupyter nbconvert --to notebook --execute ml/notebooks/<name>.ipynb --inplace`.

Current finding (02, synthetic data): LightGBM does not beat the customer-history baseline
(MAE 2.92 vs 2.83 days late), so WP-05 uses the baseline until real shop data says otherwise.

Current finding (03, CPU baseline, `artifacts/injection_metrics_cpu_baseline.json`):
DistilBERT-multilingual, 4 epochs, public rows capped at 400 per split. The checkpoint and the
threshold are chosen on held-out *training* families; the test split is scored once. On the six
unseen Hishab families (EN/BN/Banglish/ZH, 48 rows) AUC is 0.69: recall 100% needs a threshold so
low (0.10) that it also flags every statement row and 7 in 8 report requests (precision 0.57).
Public English test: F1 0.90, AUC 0.99 (that data is easy). So the classifier cannot be the guard
alone; WP-11's rules run first, and Labib's Kaggle GPU run (mDeBERTa, all public rows) is the one
to compare. An earlier note quoting "recall 96%" picked the threshold on the test split, which
makes recall a given; ignore it.
