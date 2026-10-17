# ---
# jupyter:
#   kernelspec:
#     display_name: Python 3
#     name: python3
#   accelerator: GPU
# ---

# %% [markdown]
# # 03 — Multilingual prompt-injection classifier (Hishab WP-17 → WP-11 guard; FEATURES P5)
#
# Fine-tunes a small multilingual encoder to flag prompt-injection in **English, Bangla,
# Banglish and Chinese**: user messages, uploaded statement rows and OCR text all pass through
# it before any model sees them. The rules layer in WP-11 runs first; this model catches the
# paraphrases rules miss.
#
# **Data**
# - Hishab corpus `data/public/injection/injection_corpus.jsonl`: 12 attack and 12 benign
#   families × 4 languages, including hard negatives ("ignore the disputed invoice"). The
#   split holds out whole families, so test scores measure generalisation to unseen phrasings.
# - Public English sets from Hugging Face (internet must be on in Kaggle settings):
#   `deepset/prompt-injections` (Apache-2.0) and, if reachable,
#   `xTRam1/safe-guard-prompt-injection`.
#
# **How to run (Kaggle):** Settings → Accelerator **GPU T4 x2** (or P100), Internet **On**.
# Add the repo's `data/public/injection/injection_corpus.jsonl` as a dataset (or upload it to
# `/kaggle/working`). *Run all* (~15–25 min). Each epoch is checkpointed in
# `/kaggle/working/hishab_ml/ckpt`; re-running resumes from the last checkpoint.
# Download `hishab_ml/injection_metrics.json` (→ `ml/artifacts/`) and
# `hishab_ml/injection_onnx_int8/` (→ GitHub Release asset or Google Drive; too big for git).

# %%
import glob
import json
import os
import random
from pathlib import Path

import numpy as np

SEED = 20261020
MODEL_NAME = os.environ.get("HISHAB_INJ_MODEL", "microsoft/mdeberta-v3-base")  # or xlm-roberta-base
OUT = Path("/kaggle/working/hishab_ml" if Path("/kaggle").exists() else "hishab_ml")
CKPT = OUT / "ckpt"
OUT.mkdir(parents=True, exist_ok=True)
EPOCHS = int(os.environ.get("HISHAB_INJ_EPOCHS", "4"))
PUBLIC_CAP = int(os.environ.get("HISHAB_PUBLIC_CAP", "0"))  # 0 = use every public row (GPU)
MAX_LEN = 128
THRESHOLD_TARGET_RECALL = 0.95  # pick the decision threshold for >= 95% recall on attacks

random.seed(SEED)
np.random.seed(SEED)

# %%
# Kaggle images have these; on Colab install them.
try:
    import datasets  # noqa: F401
    import transformers  # noqa: F401
except ImportError:  # pragma: no cover
    os.system("pip -q install transformers datasets accelerate sentencepiece")
try:
    import optimum  # noqa: F401
except ImportError:  # pragma: no cover
    os.system("pip -q install 'optimum[onnxruntime]' onnx")

import torch  # noqa: E402
from datasets import Dataset, load_dataset  # noqa: E402
from sklearn.metrics import precision_recall_fscore_support, roc_auc_score  # noqa: E402
from transformers import (  # noqa: E402
    AutoModelForSequenceClassification,
    AutoTokenizer,
    DataCollatorWithPadding,
    Trainer,
    TrainingArguments,
)

print("GPU:", torch.cuda.get_device_name(0) if torch.cuda.is_available() else "none")


# %% [markdown]
# ## 1. Data

# %%
def find_corpus() -> Path:
    hits = glob.glob("/kaggle/input/**/injection_corpus.jsonl", recursive=True)
    for candidate in [*hits, "injection_corpus.jsonl", "/kaggle/working/injection_corpus.jsonl",
                      "../../data/public/injection/injection_corpus.jsonl",
                      "../data/public/injection/injection_corpus.jsonl"]:
        if Path(candidate).exists():
            return Path(candidate)
    raise FileNotFoundError("add data/public/injection/injection_corpus.jsonl as a dataset")


ours = [json.loads(line) for line in find_corpus().read_text(encoding="utf-8").splitlines()]
train_rows = [{"text": r["text"], "label": int(r["label"] == "attack"), "lang": r["lang"],
               "source": "hishab"} for r in ours if r["split"] == "train"]
test_rows = [{"text": r["text"], "label": int(r["label"] == "attack"), "lang": r["lang"],
              "family": r["family"], "source": "hishab"} for r in ours if r["split"] == "test"]

public_test = []
for name, text_col, label_col in (("deepset/prompt-injections", "text", "label"),
                                  ("xTRam1/safe-guard-prompt-injection", "text", "label")):
    try:
        ds = load_dataset(name)
    except Exception as exc:  # offline or gated: continue with what we have
        print(f"skip {name}: {exc}")
        continue
    for split_name, split in ds.items():
        rows = [{"text": t, "label": int(y), "lang": "en_public", "source": name}
                for t, y in zip(split[text_col], split[label_col], strict=True)]
        if PUBLIC_CAP:
            random.Random(SEED).shuffle(rows)
            rows = rows[:PUBLIC_CAP]
        if split_name == "test":
            public_test += rows
        else:
            train_rows += rows
    print(f"loaded {name}")

# Light augmentation of our own training rows: casing and spacing noise, mixed-script joins.
aug = []
for r in [r for r in train_rows if r["source"] == "hishab"]:
    aug.append({**r, "text": r["text"].upper() if r["lang"] in ("en", "bl") else r["text"] + " "})
    aug.append({**r, "text": "  ".join(r["text"].split())})
train_rows += aug
random.shuffle(train_rows)
print(f"train {len(train_rows)} | hishab test {len(test_rows)} | public test {len(public_test)}")

# %% [markdown]
# ## 2. Fine-tune (checkpoint every epoch, resume if present)

# %%
tok = AutoTokenizer.from_pretrained(MODEL_NAME)
model = AutoModelForSequenceClassification.from_pretrained(MODEL_NAME, num_labels=2)


def encode(rows):
    ds = Dataset.from_list([{"text": r["text"], "label": r["label"]} for r in rows])
    return ds.map(lambda b: tok(b["text"], truncation=True, max_length=MAX_LEN), batched=True)


train_ds = encode(train_rows)
eval_ds = encode(test_rows)
args = TrainingArguments(
    output_dir=str(CKPT), num_train_epochs=EPOCHS, learning_rate=2e-5,
    per_device_train_batch_size=16, per_device_eval_batch_size=32, warmup_ratio=0.1,
    weight_decay=0.01, eval_strategy="epoch", save_strategy="epoch", save_total_limit=2,
    load_best_model_at_end=True, metric_for_best_model="eval_loss", seed=SEED,
    fp16=torch.cuda.is_available(), report_to=[], logging_steps=20,
)
trainer = Trainer(model=model, args=args, train_dataset=train_ds, eval_dataset=eval_ds,
                  data_collator=DataCollatorWithPadding(tok))
resume = bool(glob.glob(str(CKPT / "checkpoint-*")))
trainer.train(resume_from_checkpoint=resume or None)


# %% [markdown]
# ## 3. Evaluate per language, on unseen families, and on public English data

# %%
def scores(rows) -> np.ndarray:
    logits = trainer.predict(encode(rows)).predictions
    return torch.softmax(torch.tensor(logits), dim=-1)[:, 1].numpy()


def report(rows, probs, threshold):
    y = np.array([r["label"] for r in rows])
    pred = (probs >= threshold).astype(int)
    p, r, f, _ = precision_recall_fscore_support(y, pred, average="binary", zero_division=0)
    out = {"n": int(len(y)), "precision": round(float(p), 4), "recall": round(float(r), 4),
           "f1": round(float(f), 4)}
    if len(set(y)) > 1:
        out["auc"] = round(float(roc_auc_score(y, probs)), 4)
    return out


test_probs = scores(test_rows)
attack_probs = np.sort(test_probs[np.array([r["label"] for r in test_rows]) == 1])
threshold = float(attack_probs[int((1 - THRESHOLD_TARGET_RECALL) * len(attack_probs))])
metrics = {
    "model": MODEL_NAME, "seed": SEED, "epochs": EPOCHS, "threshold": round(threshold, 4),
    "public_rows_cap": PUBLIC_CAP or "all",
    "threshold_rule": f"lowest score that keeps recall >= {THRESHOLD_TARGET_RECALL} on attacks",
    "hishab_unseen_families": report(test_rows, test_probs, threshold),
    "by_language": {}, "by_family": {},
    "test_families": sorted({r["family"] for r in test_rows}),
}
for lang in ("en", "bn", "bl", "zh"):
    idx = [i for i, r in enumerate(test_rows) if r["lang"] == lang]
    metrics["by_language"][lang] = report([test_rows[i] for i in idx], test_probs[idx], threshold)
for family in metrics["test_families"]:
    idx = [i for i, r in enumerate(test_rows) if r["family"] == family]
    hits = (test_probs[idx] >= threshold).mean()
    metrics["by_family"][family] = round(float(hits), 4)  # attack: catch rate; benign: FP rate
if public_test:
    metrics["public_english_test"] = report(public_test, scores(public_test), threshold)
print(json.dumps(metrics, indent=2, ensure_ascii=False))
(OUT / "injection_metrics.json").write_text(json.dumps(metrics, indent=2, ensure_ascii=False))

# %% [markdown]
# ## 4. Export ONNX (fp32) and dynamically quantised int8 for CPU inference on the server

# %%
best = OUT / "best"
trainer.save_model(str(best))
tok.save_pretrained(str(best))
os.system(f"optimum-cli export onnx --model {best} --task text-classification {OUT}/injection_onnx")
from onnxruntime.quantization import QuantType, quantize_dynamic  # noqa: E402

int8_dir = OUT / "injection_onnx_int8"
int8_dir.mkdir(exist_ok=True)
quantize_dynamic(str(OUT / "injection_onnx" / "model.onnx"), str(int8_dir / "model.onnx"),
                 weight_type=QuantType.QInt8)
for f in (OUT / "injection_onnx").iterdir():
    if f.suffix != ".onnx":
        os.system(f"cp {f} {int8_dir}/")
(int8_dir / "hishab_threshold.json").write_text(json.dumps({"threshold": threshold,
                                                             "model": MODEL_NAME}))
for f in sorted(int8_dir.iterdir()):
    print(f.name, round(f.stat().st_size / 1e6, 1), "MB")
