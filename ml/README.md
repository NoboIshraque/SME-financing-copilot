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
