# AI models in DecisionGuard: what they do, and how to switch them on

For Nobo. Plain English, no code needed. Written 20 Oct 2026 (Session A).

## The one-line version

The copilot works **with no AI model at all**. Models only make it sound more natural and add a
second opinion. Every number always comes from our own engines and is re-checked before anyone
sees it, whether models are on or off.

## Who does what

| Job | Model | Where it runs | What it does |
| --- | --- | --- | --- |
| **Brain** | Gemini 2.5 Flash (Google) | Google's free API | Reads the question and picks what to look up (cash, bills, loans...). Writes the final sentence from the checked statements. |
| **Voters** | gpt-oss-120b, Qwen 3 32B (backups: gpt-oss-20b, Gemma 3) | Groq's free API (Gemma on Google) | On bigger decisions (a loan, a netting round), vote on whether the engine's top choice is right. |
| **Critic** | Qwen 3 32B (backups as above) | Groq | Writes "the case against" the advice. Never from the same company as the brain. |
| **Rules** (deterministic planner) | none, it's our code | our server | Does all of the above with keyword rules. Always available. Last step of every chain. |

**What the models see:** only anonymised text. Before anything leaves the server, names, phone
numbers, account numbers and other personal details are replaced with tokens ("Customer 1"),
and the gateway (`backend/app/llm/gateway.py`) refuses to send anything that still looks
personal. Models never see the ledger, never compute a number, and never move money.

**What happens to what they say:** if a model writes a number that our checker cannot match to
a verified figure, the model's sentence is thrown away and the plain checked statements are
shown instead. If the voters disagree with the engine on a big decision, the copilot says
"the models disagreed, so I won't guess" rather than pick a side.

## The three modes (`LLM_MODE`)

| Mode | What happens | Used for |
| --- | --- | --- |
| `fixtures` (the hosted site today) | No model is ever called. Two recorded planner answers are replayed; every other question goes to the rules. | Tests, CI, the free hosted demo |
| `deterministic` | Rules only, no models, no recordings. | Fully offline demo |
| `live` | Real Gemini and Groq calls, with the rules as the fallback. | Judging, if you want the multi-model features visible |

With **no keys**, `live` behaves like `deterministic`: each model is skipped ("no key") and the
rules answer.

## What changes when you switch to `live`

- Answers read more naturally (Gemini writes the sentence from the checked statements).
- The "N of 3 models agree" box and the critic's "case against" come from real, different models.
- Answers are slower: a few seconds per question instead of under one.
- On a big decision the voters may disagree and the copilot then abstains on purpose. That is
  the feature working, but it can surprise you in a live demo.

## Free-tier limits and what happens when we hit them

We stay under the free tiers ourselves (`backend/app/llm/providers.py`), so the providers never
have to refuse us:

| Model | Our limit per minute | Our limit per day |
| --- | --- | --- |
| Gemini 2.5 Flash | 10 | 250 |
| Each Groq model | 30 | 1,000 |
| Gemma 3 | 30 | 14,000 |

One question uses about 2 Gemini calls (plan and wording) and 0 to 4 Groq calls (only big
decisions get votes and a critic). That is roughly **5 questions a minute, about 120 a day** on
Gemini. A model that fails or is busy rests for 30 seconds to 10 minutes. In every one of these
cases the next model in line answers, and at the end of the line the rules answer. **The copilot
never stops answering because of a limit.** It just sounds plainer.

## Are the rules good enough to be the fallback?

Yes, as of today. The 67 everyday questions in `backend/tests/agents/test_everyday_questions.py`
(English, Bangla, Banglish and Chinese: cash, salaries, bills, who owes me, loans, profit,
what-ifs, debts with other shops, reminders, greetings) all plan correctly with the rules alone.
This morning 30 of them got "I can't answer that one yet". The offline evaluation passes 70 of 70 tasks with no model.

**Recommendation: switching to `live` for judging is safe.** If a provider rate-limits during
the session, the rules take over and every one of those questions still gets an answer. If live
answers feel slow, or "the models disagreed" shows up too often, switch back to `fixtures` (same
steps, one value) and nothing else changes.

## Switching live models on in Render (about 5 minutes)

1. Get the keys (free, no card needed):
   - Gemini: <https://aistudio.google.com/apikey>, "Create API key".
   - Groq: <https://console.groq.com/keys>, "Create API Key".
2. Open the Render dashboard, then the **decisionguard-api** service, then the **Environment** tab.
3. Set `LLM_MODE` to `live`.
4. Fill `GEMINI_API_KEY` and `GROQ_API_KEY` with the two keys. (They are marked "sync: false" in
   `render.yaml`, so they live only in the dashboard and never in the repository.)
5. Click **Save Changes**. Render restarts the API (a minute or two).
6. Check it worked: open `https://decisionguard-api.onrender.com/api/health`. Under `config` you
   should see `"llm_mode": "live"`, `"gemini_key_set": true` and `"groq_key_set": true`. The
   page never shows the keys themselves.
7. Ask the copilot "Will I run out of cash next month?". In live mode the answer usually reads as
   one flowing paragraph instead of a list of short statements.

To switch back: set `LLM_MODE` to `fixtures` and save. You can leave the keys in place.

**Never** put the keys in a file in the repository, in a chat, or in a screenshot. If a key
leaks, delete it in the provider's console and make a new one.

## Checking the keys from a laptop (optional)

With the keys in `backend/.env` (git-ignored), this sends one anonymised test question per model
and records the answers as evidence:

```
uv --directory backend run python -m app.llm.live_check
```

## Where to look in the code

- Roles, models, limits, fallback order: `backend/app/llm/providers.py`
- The only door to a model (privacy gate, budgets, fallback): `backend/app/llm/gateway.py`
- The rules (keywords per intent, in four writing styles): `backend/app/llm/deterministic.py`
- Number checking: `backend/app/agents/checker.py`
