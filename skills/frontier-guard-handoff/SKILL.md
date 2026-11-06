---
name: frontier-guard-handoff
description: >-
  Universal Quota-Preserving Adaptive Delegator v3.1 ("Frontier-Guard-Handoff")
  for Google Antigravity workflows across all domains (Backend, Frontend/UI,
  Data/SQL, DevOps, and Research/Writing). Enforces cheap-by-default execution,
  Anti-Recursion Worker Guards, Blueprint-Only Frontier invocations (Opus 5.5 /
  Gemini Argon), Style-Clone Anchors, Adversarial Test Seeding, Fast-Path Inline
  Bypass for micro-edits, and an instant per-prompt kill-switch via `/direct`
  (or `/max`, `/frontier`, `/bypass`, `/off`, `/no-delegate`).
---

# Universal Quota-Preserving Adaptive Delegator v3.1 (`frontier-guard-handoff`)

## 0. Subagent Worker Anti-Recursion Guard (Rule #0.1)

> [!CAUTION]
> **SUBAGENT WORKER TERMINATION GUARD (MANDATORY)**
> If you are a spawned subagent (i.e., your prompt contains `<subtask_envelope>` or `[WORKER_MODE]`, or you were invoked to execute a specific subtask):
> - **DO NOT** delegate further or spawn sub-subagents.
> - **DO NOT** invoke `invoke_subagent` or `define_subagent`.
> - Execute the assigned task directly, run the verification command, and return `<subtask_result>`.
>
> **Structural Recursion Prevention**: When configuring worker agents via `define_subagent`, always set `EnableSubagentTools: false` so that recursive subagent dispatch is structurally impossible in the runtime.

---

## 1. Instant Per-Prompt Kill-Switch (`/direct`, `/max`, `/frontier`, `/bypass`, `/off`, `/no-delegate`)

> [!IMPORTANT]
> **PER-PROMPT OVERRIDE RULE**
> If the user's message contains any of the following standalone slash-keywords anywhere in the prompt:
> - **`/direct`** (Primary override keyword)
> - **`/max`**
> - **`/frontier`**
> - **`/bypass`**
> - **`/off`**
> - **`/no-delegate`**
>
> *(Evaluated with boundary-aware regex `(?:^|(?<=\s))(/[a-zA-Z0-9_-]+)(?=\s|$|[.,!?;:])` to prevent mid-path false positives like `src/direct/foo.ts` or URLs)*
>
> **ACTION:** Immediately **SUSPEND** `frontier-guard-handoff` for that entire turn.
> - Do **NOT** offload subtasks to `flash` or `flash_lite`.
> - Do **NOT** cap output tokens to blueprints.
> - Execute 100% of the coding, reasoning, or writing inline using the active flagship model (Opus 5.5 / Gemini Argon).
> - Automatically re-arm `frontier-guard-handoff` on the next user prompt that omits the bypass keyword.

---

## 2. Fast-Path Inline Bypass (Anti-Overhead Guard)

Subagent orchestration has a ~1.5–2.5s startup cost. Do **NOT** spawn background workers when inline execution is cheaper and faster.

**Execute INLINE immediately (no subagent dispatch) if ANY of the following hold:**
1. The user included `/direct`, `/max`, `/frontier`, `/bypass`, `/off`, or `/no-delegate`.
2. The request is a conversational question, explanation, or <300-token answer.
3. The task modifies **1 file** with an estimated diff of **`<= 35 lines`** of code/text.
4. Executing a single diagnostic CLI command or reading 1–2 files.

For all multi-file, boilerplate-heavy, or high-token generation workloads (`> 35 lines` or `>= 2 files`), enforce the **Adaptive Delegation Pipeline** below.

---

## 3. Deterministic 5-Factor Complexity Scorer ($C \in [0.00, 1.00]$)

Compute the task's **Complexity Score $C$** before dispatching:

$$C = 0.25(\text{Coupling}) + 0.25(\text{Concurrency}) + 0.20(\text{Novelty}) + 0.15(\text{BlastRadius}) + 0.15(\text{Irreversibility})$$

All 5 factors are strictly validated and clamped to $[0.00, 1.00]$.

| Score Range | Target Tier | Execution Strategy |
| :--- | :--- | :--- |
| **$C < 0.25$** | **Tier 1 (`flash_lite`)** | Direct async background offload (`invoke_subagent(Model="flash_lite")`). Zero Frontier tokens. |
| **$0.25 \le C < 0.55$** | **Tier 2 (`flash`)** | Async offload (`invoke_subagent(Model="flash")`) + **15-line Style-Clone Anchor** + Automated Verification Gate. |
| **$C \ge 0.55$** | **Tier 3 Blueprint (`opus_5_5` / `argon`) -> Tier 2 Fan-Out** | Emits a **`<= 350`-token Blueprint + 3–5 Adversarial Edge Vectors** -> Fan out heavy generation to `flash` asynchronously -> Verify + **`<= 80`-token Frontier Micro-Audit** on final diff. |

---

## 4. Universal Multi-Domain Adapters

`frontier-guard-handoff` adapts its Blueprint, Worker Offload, and Verification Gate across **all 5 core domains**:

| Domain | Tier 3 Frontier Blueprint (`<= 350` tok) | Tier 1/2 Worker Offload (`flash` / `flash_lite`) | Automated Verification Gate |
| :--- | :--- | :--- | :--- |
| **1. Polyglot Software (TS, Py, Rust, Go, C++, Java, C#)** | State invariants, concurrency locks, interface contracts, <=12-line pseudocode, 3–5 adversarial test vectors. | Full implementation bodies, imports, error wrappers, unit/property tests, docstrings. | Compiler/typecheck (`tsc`, `pytest`, `cargo check`, `go test`, `dotnet build`, `mvn test`). |
| **2. Frontend UI / CSS / 3D / Motion** | Aesthetic direction, CSS grid/flex geometry, animation easing curves, state-machine transitions, accessibility requirements. | JSX/HTML component scaffolding, Tailwind/CSS rules, SVG/Three.js boilerplate, responsive breakpoints. | Typecheck + DOM/Console error check + a11y contrast & landmark audit. |
| **3. Data Engineering / SQL / Spark / dbt** | Grain definition, join cardinality guards, partitioning/clustering strategy, window-function logic. | Full SQL/SQLX/dbt models, schema YAML files, data-cleaning regexes, PySpark boilerplate. | SQL dry-run (`bq query --dry_run` / `EXPLAIN`), row-count & null-invariant assertions. |
| **4. DevOps / IaC (Terraform, K8s, CI/CD)** | IAM least-privilege boundary, network topology, rollback safety invariants. | HCL resource blocks, GitHub Actions YAML, Dockerfile multi-stage boilerplate, Helm templates. | `terraform validate`, `kubectl --dry-run=client`, YAML schema lint. |
| **5. Deep Research / Strategy / Writing** | Core thesis, analytical framework, counter-arguments, section outline, falsifiable claims checklist. | Parallel web/doc fetching (`research` subagent on `flash`), section drafting, formatting, tables. | **Citation & Claim Audit**: Verify every quantitative claim maps to a retrieved source URL/file. |

---

## 5. Strict Frontier-Tier Gatekeeping (Opus 5.5 / Argon Firewall)

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

## 6. Surgical Context Slicing + Style-Clone Protocol

Never pass chat history or whole dependency files to a subagent. Use `scripts/context_slicer.py` to construct a compact, XML-valid `<subtask_envelope>` (`< 1,500` tokens):

1. **Zero Chat History**: Strip all prior conversation turns and unrelated tool outputs.
2. **Polyglot Signature Slicing**:
   - Python (`.py`): Parsed via `ast.parse()` to extract complete parameter lists, type annotations, return types, and class methods.
   - TypeScript (`.ts`, `.tsx`): Extracts entire `interface`, `enum`, and `type` blocks (up to 25 lines) and balances multi-line function signatures up to `;`.
   - Rust, Go, Java, C#, C++, SQL, HCL: Multi-line balanced signatures up to `{` or `;`.
3. **15-Line Style-Clone Anchor**: Attach one 15-line snippet from an existing file in the repo so `flash` mirrors the exact local error-handling, logging, and formatting conventions.
4. **Adversarial Test Seeds**: Attach the 3–5 edge cases generated by the Frontier blueprint.
5. **XML CDATA Wrappers**: All signatures, anchor snippets, objectives, and test commands are wrapped in `<![CDATA[ ... ]]>` to prevent generics (`Result<T, E>`) or shell operators (`&&`) from corrupting the envelope XML.

---

## 7. Asynchronous Non-Blocking Execution Lifecycle

1. **Partition into Background vs. Local Sets**:
   - **Set A (Background Subagents)**: Isolated module coding, unit tests, data formatting, docstrings, parallel web/codebase research.
   - **Set B (Immediate Local Orchestrator Work)**: Directory creation, config updates, barrel exports (`index.ts`), dependency installation, or inline edits to the main entry file.
2. **Dispatch & Continue**:
   - Launch Set A via `invoke_subagent` with `Model: "flash"` or `Model: "flash_lite"`.
   - Immediately execute Set B locally in the same workflow without waiting or polling.
3. **Reactive Wakeup & Verification**:
   - Let Antigravity reactively wake the orchestrator when background subagents complete, then run the domain Verification Gate (`tsc`, `pytest`, `dry_run`, etc.).

---

## 8. Antigravity Tool & Configuration Bindings

### 8.1 Configuration Schema (`.agents/frontier-guard.config.json`)
```json
{
  "version": "3.1.0",
  "quality_profile": "ZERO_REGRESSION",
  "override_keywords": [
    "/direct",
    "/max",
    "/frontier",
    "/bypass",
    "/off",
    "/no-delegate"
  ],
  "allow_any_slash_keyword_override": false,
  "subagent_anti_recursion_guard": true,
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
  },
  "context_hygiene": {
    "strip_chat_history": true,
    "strip_global_system_prompt": true,
    "ast_signature_only_for_deps": true,
    "require_style_clone_anchor": true,
    "require_adversarial_test_seeds": true
  }
}
```

### 8.2 Native Antigravity Tool Call Mappings

> [!NOTE]
> `dispatch_subagent`, `check_subtask_status`, and `escalate_to_frontier` are **Logical Protocol Operations**. They map to native Google Antigravity tools as follows:

#### Operation 1: `dispatch_subagent` -> Native `invoke_subagent`
To launch an async worker without recursion risk:
```json
// Optional structural safety: define worker with subagent tools disabled
{
  "tool": "define_subagent",
  "parameters": {
    "Name": "stateless-worker",
    "Description": "Non-recursive worker subagent for leaf tasks",
    "EnableSubagentTools": false,
    "EnableWriteTools": true,
    "SystemPrompt": "You are a direct execution worker. Implement the subtask envelope, verify, and return <subtask_result>. DO NOT attempt to spawn subagents."
  }
}

// Dispatch worker via native invoke_subagent
{
  "tool": "invoke_subagent",
  "parameters": {
    "TypeName": "self",
    "Role": "Module Implementer",
    "Model": "flash",
    "Workspace": "inherit",
    "Prompt": "<subtask_envelope id=\"sub-01\" tier=\"tier2_flash\">...</subtask_envelope>"
  }
}
```

#### Operation 2: `check_subtask_status` -> Native Reactive Wakeup
Antigravity automatically delivers messages when a subagent finishes. You do **NOT** poll in a loop.
If inspecting tasks programmatically:
```json
{
  "tool": "manage_subagents",
  "parameters": {
    "Action": "list"
  }
}
```

#### Operation 3: `escalate_to_frontier` -> Frontier Blueprint Protocol
The escalation mechanism depends on the **Active Primary Model**:

| Primary Session Model | Escalation Implementation |
| :--- | :--- |
| **Opus 5.5 / Gemini Argon (Flagship)** | **Execute INLINE**: Synthesize the `<= 350`-token Blueprint and 3–5 edge vectors directly in the current turn, then call `invoke_subagent(Model="flash")` to offload boilerplate generation. |
| **Flash / Flash-Lite (Tier 1/2 Primary)** | Call `invoke_subagent` with `Model: "pro"`: <br>`invoke_subagent(TypeName="self", Role="Frontier Blueprint Architect", Model="pro", Prompt="Generate <= 350 token blueprint...")` |

---

## 9. Automated Verification & Testing

Verify the context slicer and test suite at any time:
```powershell
python scripts/context_slicer.py test
```
All 7 test suites validate:
1. Regex kill-switch detection and mid-path / URL false-positive rejection
2. Configuration auto-loading from `.agents/frontier-guard.config.json`
3. 5-factor complexity scoring, input clamping, and `ValueError` boundaries
4. Python AST multi-line parameter and method signature extraction
5. TypeScript full `interface`, `enum`, and `type` block extraction
6. Rust, Go, Java, and SQL multi-line signature parenthesis balancing
7. XML CDATA encapsulation and `xml.etree.ElementTree` validation
