---
name: frontier-guard-handoff
description: >-
  Universal Quota-Preserving Adaptive Delegator v3.0 ("Frontier-Guard-Handoff")
  for Google Antigravity workflows across all domains (Backend, Frontend/UI,
  Data/SQL, DevOps, and Research/Writing). Enforces cheap-by-default execution,
  Blueprint-Only Frontier invocations (Opus 5.5 / Gemini Argon), Style-Clone
  Anchors, Adversarial Test Seeding, Fast-Path Inline Bypass for micro-edits,
  and an instant per-prompt kill-switch via `/direct` (or `/max`, `/frontier`).
---

# Universal Quota-Preserving Adaptive Delegator v3.0 (`frontier-guard-handoff`)

## 0. Instant Per-Prompt Kill-Switch (`/direct`, `/max`, `/frontier`, `/bypass`)

> [!IMPORTANT]
> **PER-PROMPT OVERRIDE RULE**
> If the user's message contains any of the following slash-keywords anywhere in the prompt:
> - **`/direct`** (Primary keyword)
> - **`/max`**
> - **`/frontier`**
> - **`/bypass`**
>
> **ACTION:** Immediately **SUSPEND** `frontier-guard-handoff` for that entire turn.
> - Do **NOT** offload subtasks to `flash` or `flash_lite`.
> - Do **NOT** cap output tokens to blueprints.
> - Execute 100% of the coding, reasoning, or writing inline using the active flagship model (Opus 5.5 / Gemini Argon).
> - Automatically re-arm `frontier-guard-handoff` on the next user prompt that omits the bypass keyword.

---

## 1. Fast-Path Inline Bypass (Anti-Overhead Guard)

Subagent orchestration has a ~1.5–2.5s startup cost. Do **NOT** spawn background workers when inline execution is cheaper and faster.

**Execute INLINE immediately (no subagent dispatch) if ANY of the following hold:**
1. The user included `/direct`, `/max`, `/frontier`, or `/bypass`.
2. The request is a conversational question, explanation, or <300-token answer.
3. The task modifies **1 file** with an estimated diff of **`<= 35 lines`** of code/text.
4. Executing a single diagnostic CLI command or reading 1–2 files.

For all multi-file, boilerplate-heavy, or high-token generation workloads (`> 35 lines` or `>= 2 files`), enforce the **Adaptive Delegation Pipeline** below.

---

## 2. Deterministic 5-Factor Complexity Scorer ($C \in [0.00, 1.00]$)

Compute the task's **Complexity Score $C$** before dispatching:

$$C = 0.25(\text{Coupling}) + 0.25(\text{Concurrency}) + 0.20(\text{Novelty}) + 0.15(\text{BlastRadius}) + 0.15(\text{Irreversibility})$$

| Score Range | Target Tier | Execution Strategy |
| :--- | :--- | :--- |
| **$C < 0.25$** | **Tier 1 (`flash_lite`)** | Direct async background offload (`invoke_subagent(Model="flash_lite")`). Zero Frontier tokens. |
| **$0.25 \le C < 0.55$** | **Tier 2 (`flash` / `haiku`)** | Async offload (`invoke_subagent(Model="flash")`) + **15-line Style-Clone Anchor** + Automated Verification Gate. |
| **$C \ge 0.55$** | **Tier 3 Blueprint (`opus_5_5` / `argon`) -> Tier 2 Fan-Out** | Frontier emits a **`<= 350`-token Blueprint + 3–5 Adversarial Edge Vectors** -> Fan out heavy generation to `flash` asynchronously -> Verify + **`<= 80`-token Frontier Micro-Audit** on final diff. |

---

## 3. Universal Multi-Domain Adapters

`frontier-guard-handoff` adapts its Blueprint, Worker Offload, and Verification Gate across **all 5 core domains**:

| Domain | Tier 3 Frontier Blueprint (`<= 350` tok) | Tier 1/2 Worker Offload (`flash` / `flash_lite`) | Automated Verification Gate |
| :--- | :--- | :--- | :--- |
| **1. Polyglot Software (TS, Py, Rust, Go, C++, Java, C#)** | State invariants, concurrency locks, interface contracts, <=12-line pseudocode, 3–5 adversarial test vectors. | Full implementation bodies, imports, error wrappers, unit/property tests, docstrings. | Compiler/typecheck (`tsc`, `pytest`, `cargo check`, `go test`, `dotnet build`, `mvn test`). |
| **2. Frontend UI / CSS / 3D / Motion** | Aesthetic direction, CSS grid/flex geometry, animation easing curves, state-machine transitions, accessibility requirements. | JSX/HTML component scaffolding, Tailwind/CSS rules, SVG/Three.js boilerplate, responsive breakpoints. | Typecheck + DOM/Console error check + a11y contrast & landmark audit. |
| **3. Data Engineering / SQL / Spark / dbt** | Grain definition, join cardinality guards, partitioning/clustering strategy, window-function logic. | Full SQL/SQLX/dbt models, schema YAML files, data-cleaning regexes, PySpark boilerplate. | SQL dry-run (`bq query --dry_run` / `EXPLAIN`), row-count & null-invariant assertions. |
| **4. DevOps / IaC (Terraform, K8s, CI/CD)** | IAM least-privilege boundary, network topology, rollback safety invariants. | HCL resource blocks, GitHub Actions YAML, Dockerfile multi-stage boilerplate, Helm templates. | `terraform validate`, `kubectl --dry-run=client`, YAML schema lint. |
| **5. Deep Research / Strategy / Writing** | Core thesis, analytical framework, counter-arguments, section outline, falsifiable claims checklist. | Parallel web/doc fetching (`research` subagent on `flash`), section drafting, formatting, tables. | **Citation & Claim Audit**: Verify every quantitative claim maps to a retrieved source URL/file. |

---

## 4. Strict Frontier-Tier Gatekeeping (Opus 5.5 / Argon Firewall)

> [!CAUTION]
> **BANNED ON FRONTIER MODELS (Unless `/direct` is active)**
> Never burn Opus 5.5 or Argon output tokens on:
> - Writing raw boilerplate, DTOs, CRUD scaffolds, or config files (`JSON`/`YAML`/`TOML`)
> - Writing full unit test files or mock fixtures (Frontier only emits 3–5 bullet *Adversarial Edge Vectors*)
> - Data formatting, CSV/JSON/Markdown table serialization, or regex construction
> - Linear script refactoring, symbol renaming, file splitting, or barrel exports (`index.ts`)
> - Routine docstrings, JSDoc/TSDoc, READMEs, or inline comments
> - Syntax error fixes or mechanical linter remediation

> [!IMPORTANT]
> **PERMITTED FRONTIER MODES (Strictly Token-Capped)**
> 1. `BLUEPRINT_ONLY` (`<= 350` output tokens): Architectural synthesis, novel algorithms, distributed concurrency state machines, UI design specs, or research thesis outlines.
> 2. `ROOT_CAUSE_DIAGNOSIS` (`<= 250` output tokens): Unlocked **only after** a Tier 2 worker fails 2 attempts with compiler/test stderr attached.
> 3. `MICRO_AUDIT` (`<= 80` output tokens): Reviews a unified `git diff` on high-blast-radius tasks (`blast_radius >= 0.8`) and outputs `VERDICT: PASS` or `VERDICT: PATCH <line>: <fix>`.

---

## 5. Surgical Context Slicing + Style-Clone Protocol

Never pass chat history or whole dependency files to a subagent. Use [`.agents/skills/frontier-guard-handoff/scripts/context_slicer.py`](file:///c:/Users/harno/.gemini/antigravity-ide/scratch/.agents/skills/frontier-guard-handoff/scripts/context_slicer.py) to construct a compact `<subtask_envelope>` (`< 1,500` tokens):

1. **Zero Chat History**: Strip all prior conversation turns and unrelated tool outputs.
2. **Polyglot Signature Slicing**: Pass only exported function/class/interface/table headers from dependency files.
3. **15-Line Style-Clone Anchor**: Attach one 15-line snippet from an existing file in the repo so `flash` mirrors the exact local error-handling, logging, and formatting conventions.
4. **Adversarial Test Seeds**: Attach the 3–5 edge cases generated by the Frontier blueprint.

---

## 6. Asynchronous Non-Blocking Execution Lifecycle

1. **Partition into Background vs. Local Sets**:
   - **Set A (Background Subagents)**: Isolated module coding, unit tests, data formatting, docstrings, parallel web/codebase research.
   - **Set B (Immediate Local Orchestrator Work)**: Directory creation, config updates, barrel exports (`index.ts`), dependency installation, or inline edits to the main entry file.
2. **Dispatch & Continue (`async: true`)**:
   - Launch Set A via `invoke_subagent` with `Model: "flash"` or `Model: "flash_lite"`.
   - Immediately execute Set B locally in the same workflow without waiting or polling.
3. **Reactive Wakeup & Verification**:
   - Let Antigravity reactively wake the orchestrator when background subagents complete, then run the domain Verification Gate (`tsc`, `pytest`, `dry_run`, etc.).

---

## 7. Antigravity Tool & Configuration Bindings

### 7.1 Configuration Schema (`.agents/frontier-guard.config.json`)
```json
{
  "version": "3.0.0",
  "override_keywords": ["/direct", "/max", "/frontier", "/bypass"],
  "fast_path_inline_bypass": {
    "max_files": 1,
    "max_changed_lines": 35
  },
  "token_budget_cap": {
    "session_total_tokens": 250000,
    "frontier_blueprint_input_cap": 6000,
    "frontier_blueprint_output_cap": 350,
    "frontier_diagnosis_output_cap": 250,
    "frontier_micro_audit_output_cap": 80,
    "worker_input_cap_per_call": 10000
  },
  "max_frontier_calls_per_run": 3,
  "auto_downgrade_threshold": {
    "quota_remaining_pct": 20,
    "complexity_score_ceiling": 0.55,
    "tier1_max_complexity": 0.25,
    "max_tier1_attempts_before_tier2": 1,
    "max_tier2_attempts_before_frontier": 2
  }
}
```

### 7.2 Tool Signatures (`dispatch_subagent`, `check_subtask_status`, `escalate_to_frontier`)

```typescript
interface DispatchSubagentArgs {
  subtask_id: string;
  domain: "code" | "ui" | "data_sql" | "devops" | "research";
  complexity_score: number;
  model_tier: "tier1_flash_lite" | "tier2_flash" | "tier2_haiku";
  role: string;
  envelope: {
    task_objective: string;
    frontier_blueprint?: string;
    dependency_signatures: string[];
    style_clone_anchor: { file_path: string; snippet: string };
    adversarial_test_seeds?: string[];
    verification_command: string;
  };
  async: true;
  workspace_mode?: "inherit" | "branch" | "share";
}

interface CheckSubtaskStatusArgs {
  subtask_ids: string[];
  wait_strategy: "non_blocking_poll" | "await_any";
  run_verification_gate: boolean;
}

interface EscalateToFrontierArgs {
  frontier_model: "claude_opus_5_5" | "gemini_argon";
  invocation_mode: "BLUEPRINT_ONLY" | "ROOT_CAUSE_DIAGNOSIS" | "MICRO_AUDIT";
  complexity_score: number;
  prior_tier_attempts?: Array<{
    subtask_id: string;
    model_used: string;
    stderr_snippet: string;
  }>;
  payload: string;
  max_output_tokens: 350 | 250 | 80;
}
```
