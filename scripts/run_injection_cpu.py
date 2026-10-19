"""Run notebook 03 (injection classifier) on a CPU, sections 1-3 only (data, fine-tune, evaluate).

Section 4 (ONNX export) and the `optimum` install it needs are skipped. This is how
`ml/artifacts/injection_metrics_cpu_baseline.json` was produced (18 Oct, orchestrator sandbox):

    uv venv mlenv --python 3.12
    uv pip install --python mlenv torch --index-url https://download.pytorch.org/whl/cpu
    uv pip install --python mlenv "transformers<5" datasets accelerate scikit-learn sentencepiece
    mkdir run && cp data/public/injection/injection_corpus.jsonl run/ && cd run
    HISHAB_INJ_MODEL=distilbert/distilbert-base-multilingual-cased HISHAB_INJ_EPOCHS=4 \\
      HISHAB_PUBLIC_CAP=400 OMP_NUM_THREADS=2 \\
      ../mlenv/bin/python -I ../scripts/run_injection_cpu.py ../ml/notebooks/03_injection_classifier.py

About 13 minutes on 2 cores. Writes run/hishab_ml/injection_metrics.json (copy it to
ml/artifacts/) and checkpoints under run/hishab_ml/ckpt (large: never commit them).
"""

import sys

src = open(sys.argv[1], encoding="utf-8").read()
src = src[: src.index("# %% [markdown]\n# ## 4. Export ONNX")]
assert src.count("    import optimum  # noqa: F401") == 1
src = src.replace("    import optimum  # noqa: F401", "    pass")
exec(compile(src, sys.argv[1], "exec"), {"__name__": "__main__"})
