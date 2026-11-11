# Frontier Guard v5 (`frontier-guard-handoff`)

Preserve flagship model quota (Claude Opus, Gemini Argon / Pro / Thinking tiers) without losing output quality:

1. **Switches (this turn only)**:
   - `/bypass`, `/direct`, `/max`, `/frontier`, `/off`, `/no-delegate` (as standalone tokens, never inside paths/URLs): suspend all delegation and run 100% inline on the active model.
   - `/lean`: lower delegation thresholds (`inline <= 15 lines / 1 file`, `delegate >= 30 lines`) for maximum quota savings.
   - **Worker anti-recursion**: if your prompt starts with `[FGH-WORKER]` or `[FGH-SCOUT]`, you are a worker—never spawn subagents; complete the brief, run its verify command, and return the compact report.

2. **Always-On Context Hygiene (biggest quota saver)**:
   - Search (`grep` / `rg`) before reading files; read line ranges instead of whole large files.
   - Cap command output (`Select-Object -First 60` / `--quiet`); never poll background tasks or subagents.
   - Batch independent tool calls into a single turn; never cap your own internal reasoning.

3. **5-Lane Deterministic Routing** (see skill `frontier-guard-handoff` or run `python scripts/fgh.py route`):
   - **L0 Tools**: Use formatters, `--fix` linters, codemods, codegen, or a short script for mechanical multi-file edits (~0 model tokens).
   - **L1 Inline**: Use the active model for design, debugging, reviews, high-risk code (auth, crypto, payments, migrations, concurrency), and small edits (`<= 40 lines` across `<= 2 files`).
   - **L2 Flash Subagents**:
     - Unknown/broad codebase search (`> 3 files`) -> `fgh-scout` (`Model: "flash"`, read-only, returns `<= 300 words` with `file:line` refs).
     - Specified + mechanically verifiable work (`>= 60 lines`) -> `fgh-worker` (`Model: "flash"`, disjoint file ownership, style anchor + verify command). Never use `flash_lite` for code.
   - **L3 External Text Lane**: Pure-text verifiable generation (unit tests, fixtures, docstrings, regexes) may run via `python scripts/fgh.py ext run` (Ollama/LM Studio local first, then OmniRoute/FreeLLMAPI with secret scrubbing), falling back to L2 on failure.
   - **Verify before trusting**: Always run the verification command yourself when a worker finishes; after 2 worker failures, take over inline.
