# Workspace Quota-Preserving Adaptive Delegator Rule (`frontier-guard-handoff` v3.1)

Always enforce the **Quota-Preserving Adaptive Delegator (`frontier-guard-handoff`)** protocol to preserve rate limits and token quota on flagship models (Claude Opus 5.5, Gemini Argon, and Thinking tiers):

0. **Subagent Anti-Recursion Guard (Rule #0.1 - Worker Termination Rule)**:
   - If you are a spawned subagent (i.e., your prompt contains `<subtask_envelope>` or `[WORKER_MODE]`, or you were invoked to implement a specific subtask), **DO NOT** delegate further or spawn sub-subagents. Execute the task directly, run the verification command, and return `<subtask_result>`.
   - Recommend using `define_subagent` with `EnableSubagentTools: false` for worker subagents so recursion is structurally impossible in runtime.

1. **Instant Per-Prompt Kill-Switch (`/direct`, `/max`, `/frontier`, `/bypass`, `/off`, `/no-delegate`)**:
   - If the user's prompt contains a standalone slash-keyword `/direct`, `/max`, `/frontier`, `/bypass`, `/off`, or `/no-delegate` (preceded by start-of-line or whitespace, NOT part of a file path or URL), **immediately disable** all downward delegation and token caps for that turn. Execute 100% of the request inline using the active flagship model.
   - Automatically re-enable delegation on the next prompt that does not contain a bypass keyword.

2. **Fast-Path Inline Bypass (Micro-Tasks)**:
   - Execute inline immediately (do not spawn subagents) when answering conversational questions, running 1–2 diagnostic commands, or editing `<= 1 file` with `<= 35 changed lines`.

3. **Cheap-by-Default Asynchronous Offloading (Multi-File / Heavy Generation)**:
   - For tasks touching `>= 2 files` or generating `> 35 lines` of boilerplate, unit tests, regexes, data formatting, UI scaffolding, SQL/IaC blocks, or documentation:
     - **BANNED on Opus 5.5 / Argon**: Raw boilerplate, unit test suites, data serialization, regex, linear refactoring, docstrings, or syntax fixes.
     - **Plan Deconstruction**: Keep architectural synthesis on the primary model as a compact **Blueprint (`<= 350` tokens)** + **3–5 Adversarial Edge Vectors**, then fan out heavy code/test/doc generation asynchronously via `invoke_subagent` with `Model: "flash"` (Tier 2) or `Model: "flash_lite"` (Tier 1).
     - **Surgical Context Slicing**: Strip chat history; pass only exported multi-line type/interface/function signatures + a **15-line Style-Clone Anchor** from an existing repo file via `scripts/context_slicer.py`.
     - **Zero-Idle Parallel Work**: While background subagents run, immediately continue local non-blocking tasks (wiring, configs, exports) and verify outputs with local compiler/test gates upon completion.
     - For full multi-domain specifications, consult `.agents/skills/frontier-guard-handoff/SKILL.md`.
