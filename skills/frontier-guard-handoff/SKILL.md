---
name: frontier-guard-handoff
description: >-
  Quota-preserving work routing for Antigravity (v5). Use on any multi-step
  coding, debugging, or research task while running on a rate-limited flagship
  model (Claude Opus, Gemini Pro / Argon / Thinking tiers) to decide what to do
  inline versus hand to deterministic tools, Flash subagents, or local/free
  models, without losing output quality. Also use when the user mentions quota,
  rate limits, token burn, delegation, Flash workers, OmniRoute, FreeLLMAPI,
  Ollama, or the /bypass, /direct, /lean switches.
---

# Frontier Guard v5

Flagship quota goes on three things, in this order:

1. **Context resent on every step.** Each tool call resends the whole conversation, every file you read, and every log you printed.
2. **Number of steps.**
3. **Output tokens.**

Quality is usually lost in three ways:

1. **Handing off work that isn't fully specified.**
2. **Accepting worker output nobody checked.**
3. **Cutting off the model's reasoning.**

This skill cuts the first list and never trades away the second.

---

## 0. Switches (check first, every turn)

| User writes | Effect for **this turn only** |
| :--- | :--- |
| `/bypass` `/direct` `/max` `/frontier` `/off` `/no-delegate` | Do everything inline with the active model. All routing and savings rules are suspended. The safety rules in §8 still apply. |
| `/lean` | Maximum savings: lower the delegation thresholds (see `config.default.json`), keep answers terse, and prefer workers for anything that is specified and verifiable. |

- A switch only counts as a standalone token at the start of the message or after whitespace. `src/direct/x.ts` and `https://a.com/max` do **not** count.
- Not sure? Run `python scripts/fgh.py switch "<prompt>"`.
- **Worker rule:** if your prompt begins with `[FGH-WORKER]` or `[FGH-SCOUT]`, you are a worker. Never delegate, never spawn subagents. Do the task, run the verify command, and return the report format from your brief.

---

## 1. Always-on habits (these save the most, even when nothing is delegated)

- **Search before you read.** Grep for the symbol first, then read only the relevant line range. Reading a whole 2,000-line file to find one function is the most expensive habit there is.
- **Keep command output short.** Pipe it through `Select-Object -First 60` / `head -60`, and use `--quiet`, `-q` or `--reporter=dot`. Never list a home or large directory recursively. Use `git ls-files | rg <pattern>` instead.
- **Batch independent tool calls** into one step.
- **Never poll.** Subagents and background tasks wake you when they finish. Kill a runaway command; don't wait on it.
- **Don't re-read what you just wrote,** and don't reprint artifacts in your reply. Link them instead.
- **Keep sessions short.** Every step resends the whole conversation, so once a phase ends (or after ~30–40 turns), suggest `/compact` or the `handoff` skill.

---

## 2. Routing: pick the cheapest lane that keeps quality

| Lane | What | Token cost to flagship |
| :--- | :--- | :--- |
| **L0 Tools** | Formatters, `--fix` linters, codemods, generators (OpenAPI, protobuf, ORM), `git mv`, small scripts | ~0 |
| **L1 Inline** | The primary model does it | Full |
| **L2 Worker** | Flash subagent: `fgh-worker` (writes) / `fgh-scout` (read-only) | The brief plus a short report |
| **L3 External** | Local or free model through `fgh.py ext` (text in, text out only) | The brief plus a verify run |
| **L4 Pro** | `invoke_subagent(Model:"pro")`, **only when the primary is not already a flagship** | A question-sized brief |

**Decision procedure.** Go through the rules in order; the first match wins. `python scripts/fgh.py route ...` implements the same rules.

1. **A switch is active** → follow §0.
2. **A deterministic tool can do it** (rename, format, lint-fix, regenerate, bulk move) → **L0**. Write a 5-line script before you consider asking a model to edit 30 files.
3. **Exploration:** "where is / how does / find all" across more than 3 files, or the location is unknown → **L2 scout**. It returns at most 300 words of findings with `file:line` references. Raw exploration output never enters your context.
4. **Small:** at most ~40 changed lines in at most 2 files → **L1**. A worker has to re-read context, so spawning one costs more than it saves.
5. **The design isn't settled** (open interfaces, trade-offs, ambiguous requirements) → **L1 for the design**. Write the decisions into a brief, then run the leftover implementation back through this list.
6. **High risk** (auth, crypto, payments, migrations, concurrency, data deletion, security boundaries, prod config) → **L1**. For big mechanical parts of a risky change: L2 plus your **full** review of the diff. **Never L3.**
7. **Specified + verifiable + ≥ ~60 output lines** → **L2 worker**. Pure-text pieces (tests, fixtures, docstrings, regexes, data files) may try **L3** first if a gateway is healthy; on failure fall back to L2.
8. **Specified but not mechanically verifiable** (prose, visual UI) → L1 if ≤ ~120 lines, else L2 plus your review.
9. **Anything else** → **L1**.

**Specifiability test:** the brief can be written in ≤ ⅓ of the expected output, and the worker makes zero judgment calls you haven't already made.
**Verifiability test:** a command decides pass or fail (tests, typecheck, lint, schema validation, dry-run).

Fails either test → it is not ready to delegate.

---

## 3. Worker setup (once per conversation)

Define two subagent types. Leaving subagent tools off makes recursion **structurally impossible**, not just discouraged.

```text
define_subagent(
  Name: "fgh-worker",
  Description: "Implements one fully specified brief, runs its verify command, returns a compact report.",
  EnableWriteTools: true, EnableSubagentTools: false,
  SystemPrompt: <contents of references/briefs.md § Worker system prompt>)

define_subagent(
  Name: "fgh-scout",
  Description: "Read-only codebase/web explorer that returns compressed findings with file:line refs.",
  EnableWriteTools: false, EnableSubagentTools: false,
  SystemPrompt: <contents of references/briefs.md § Scout system prompt>)
```

Then call `invoke_subagent(TypeName: "fgh-worker", Model: "flash", Role: "<2–5 words>", Prompt: <brief>)`.

- **No `define_subagent` available?** Use `TypeName: "self"` and start the prompt with `[FGH-WORKER]`.
- **Model choice:**
  - `flash` for any code.
  - `flash_lite` only for extraction, formatting, or summarising, never for code.
- **Parallel workers must own disjoint files.** If their files overlap, run them one after another.

---

## 4. Briefs

Generate the boilerplate with:

```bash
python scripts/fgh.py brief --goal "..." --own src/a.ts src/a.test.ts \
  --contracts src/types.ts --anchor src/b.ts:10-24 \
  --decision "Use Result<T,E>, never throw" --edge "empty input" \
  --verify "npx vitest run src/a.test.ts" --out .agents/briefs/a.md
```

A brief must contain:

- the goal
- the files the worker owns (and **nothing else** it may touch)
- contracts (signatures only)
- decisions already made
- a ≤15-line style anchor
- edge cases to cover
- the verify command
- the report format

It must **never** contain chat history, secrets, or whole files the worker doesn't need to change. See `references/briefs.md`.

---

## 5. Dispatch, overlap, merge

1. Dispatch all independent workers in **one** step.
2. Then do your own inline part immediately: the design-heavy piece, wiring, configs. Don't idle and don't poll.
3. When a report arrives:
   - **Run the verify command yourself.** It's cheap and it's the only result you can trust.
   - Run `git diff --stat`, and read only the risky hunks.
4. **Two-strike rule:** if a worker fails verification twice, take over inline using its diff as the starting point. Don't loop.
5. Optionally log the outcome so the thresholds can be tuned: `fgh.py ledger record --lane L2 --task <id> --passed true|false`.

---

## 6. When the primary is NOT a flagship

If you are Flash and you hit a real design question, ask `invoke_subagent(Model: "pro", TypeName: "fgh-scout", ...)`. Give it:

- the problem
- the constraints
- the options you considered

Ask for: a decision, the invariants, the edge cases, ≤ 400 words. Don't send implementation work to Pro. If you **are** the flagship, "escalation" just means doing the design yourself, inline.

---

## 7. External lane (summary; details in `references/external-lane.md`)

- **Text in, text out only.** The external model never edits files or runs commands. You write its output to disk and verify it.
- **Gateway order:** local first (Ollama, LM Studio), then OmniRoute / FreeLLMAPI configured with **your own official free-tier keys**.
- **Every request is secret-scrubbed.** Use `privacy: "local_only"` for proprietary code.
- **Refused automatically** for high-risk work, briefs without a verify command, or gateways the ledger has demoted.

---

## 8. Non-negotiables

- Never cap your own reasoning. Length limits apply to briefs and reports only.
- Never delegate design or root-cause analysis to a weaker model.
- Every delegated change is either verified by a command **you** ran, or reviewed by you.
- Never report token or quota savings you didn't measure.
- Never create, fetch, or store credentials on the user's behalf. Never put secrets in briefs or external requests.

---

## 9. Anti-patterns (all seen in real sessions)

| Don't | Do instead |
| :--- | :--- |
| Recursively list `C:\Users\<you>` "to find config files" | Check the 2–3 known config paths |
| Spawn a worker for a 10-line edit | Edit inline |
| Delegate "build the feature" with a vague prompt | Design inline, then delegate specified pieces |
| Re-read every file the worker wrote | Run verify + `git diff --stat`, read risky hunks |
| Poll `status` in a loop | End the turn; wake-ups are automatic |
| Hard-cap the model's output "to save tokens" | Cap briefs and reports, not reasoning |
| Retry a failing worker forever | Two strikes, then take over |
| Quote "−95% tokens" in docs | Measure with the ledger, or say nothing |

---

## Files

- `scripts/fgh.py`: CLI with `switch`, `route`, `brief`, `sig`, `scrub`, `ext health|run`, `ledger record|stats`, `install`, `selftest`. Python 3.9+, stdlib only.
- `config.default.json`: thresholds, high-risk keywords, gateways, ledger settings. Override per workspace in `.agents/fgh.config.json`.
- `references/routing.md`: worked routing examples.
- `references/briefs.md`: brief, report, worker, and scout templates.
- `references/external-lane.md`: gateway setup, provider policy, privacy, ledger.
- `assets/GEMINI.rule.md`: the compact always-on rule that `fgh.py install` writes.
