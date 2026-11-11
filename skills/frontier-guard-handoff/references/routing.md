# Routing Decision Examples (`frontier-guard-handoff` v5)

The CLI command `python scripts/fgh.py route` implements the deterministic 9-step decision tree in `SKILL.md §2`. Below are canonical examples showing why each task lands in its lane.

---

## Decision Matrix Examples

| Incoming Task | CLI Invocation | Selected Lane | Why |
| :--- | :--- | :--- | :--- |
| **"Rename `userId` to `accountId` across 25 files"** | `fgh.py route --kind mechanical --lines 180 --files 25 --tool-hint rename` | **L0-tools** | Deterministic symbol rename; a codemod or `git grep` script uses ~0 flagship tokens and cannot hallucinate. |
| **"Find where webhook retries and backoff are configured in this repo"** | `fgh.py route --kind explore --files 0 --task "find webhook retry config"` | **L2-scout** | Unknown file locations; `fgh-scout` (`flash`) searches and returns `<= 300 words` with `file:line` pointers so raw search logs never bloat flagship context. |
| **"Fix off-by-one pagination bug in `src/api/list.ts`"** | `fgh.py route --kind edit --lines 12 --files 1 --verify "npm test"` | **L1-inline** | Small change (`<= 40 lines`, `<= 2 files`); spawning a worker costs more in context re-reading than editing inline. |
| **"Design the idempotency & fencing strategy for multi-region failover"** | `fgh.py route --kind design --lines 200 --files 4 --task "idempotency failover"` | **L1-inline** | Architectural synthesis and trade-off selection require flagship reasoning. Once decided, the resulting specified modules are re-routed to L2. |
| **"Update JWT signature verification and session rotation in `src/auth/jwt.ts`"** | `fgh.py route --kind edit --lines 95 --files 2 --task "jwt signature rotation" --verify "npm test"` | **L1-inline** | Matched high-risk keywords (`jwt`, `signature`, `session`). Security-critical logic stays inline (or L2 + full diff audit). Never L3. |
| **"Implement `CsvExporter` class + edge-case tests from `types.ts`"** | `fgh.py route --kind generate --lines 140 --files 2 --spec full --verify "pytest -q" --task "csv exporter"` | **L2-worker** | Fully specified, non-high-risk, `>= 60 lines`, and mechanically verified by `pytest -q`. |
| **"Write 180 lines of unit tests for pure parser functions in `parser.py`"** | `fgh.py route --kind generate --lines 180 --files 1 --spec full --verify "pytest tests/test_parser.py" --text-only --task "parser unit tests"` | **L3-external -> L2-worker** | Stateless text output, low risk, and mechanically verified by `pytest`. Tries local/free gateway first; falls back to `fgh-worker` (`flash`) if unavailable or failing verification. |
| **"`/bypass` Refactor the billing service and write all tests inline"** | `fgh.py route --kind edit --lines 300 --files 6 --prompt "/bypass Refactor billing"` | **L1-inline** | Standalone `/bypass` switch overrides all delegation for that turn. |
| **"`/lean` Add validation helpers and unit tests (`~35 lines`)"** | `fgh.py route --kind generate --lines 35 --files 2 --spec full --verify "pytest" --prompt "/lean"` | **L2-worker** | Under `/lean`, `inline_max_lines` drops from `40 -> 15` and `delegate_min_lines` drops from `60 -> 30`. |

---

## Multi-Stage Split Pattern (Design Inline -> Fan Out Workers)

When a prompt mixes **unresolved design** with **large mechanical implementation**:

1. **Stage 1 (L1 Inline)**: Settle interfaces, data invariants, and edge cases inline on the flagship model. Write the contract file (`src/feature/types.ts`) directly.
2. **Stage 2 (L2 / L3 Parallel Fan-Out)**: Build disjoint briefs with `python scripts/fgh.py brief` and dispatch `fgh-worker` subagents in a single turn while you wire up exports/configs inline.
3. **Stage 3 (L1 Verification & Merge)**: Run the verify command yourself and inspect `git diff --stat`.
