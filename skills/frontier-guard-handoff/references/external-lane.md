# External Text Lane (`frontier-guard-handoff` v5)

## 1. How the External Lane Works

Antigravity's native `invoke_subagent` supports `inherit`, `flash_lite`, `flash`, and `pro`. External gateways (**Ollama**, **LM Studio**, **OmniRoute**, **FreeLLMAPI**) expose OpenAI-compatible `/v1/chat/completions` HTTP endpoints without tool-calling access to your workspace.

Therefore, **Lane 3 (`fgh.py ext`) is strictly a stateless text-in, text-out accelerator**:
1. You generate a self-contained brief (`python scripts/fgh.py brief ... --out .agents/briefs/task.md`).
2. You run `python scripts/fgh.py ext run --brief .agents/briefs/task.md --out path/to/target.ext --task task-01`.
3. `fgh.py` checks policy gates, scrubs secrets, sends the brief to the highest-priority healthy gateway, and extracts the fenced code into `--out`.
4. **You run the brief's verification command** (`pytest`, `tsc`, `vitest`, `cargo test`) and record the outcome (`python scripts/fgh.py ledger record --lane L3 --gateway <gw> --task task-01 --passed true|false`).
5. If `ext run` exits with code `3` (refused by policy), `4` (no gateway reachable), `5` (gateway error), or the output fails verification, **immediately fall back to an Antigravity `fgh-worker` (`Model: "flash"`)**. Never retry a failed external generation on another free model.

---

## 2. Gateway Priority & Setup

Configured in `config.default.json` (override in `.agents/fgh.config.json`):

| Priority | Gateway | Default Endpoint | Local? | Auth Env Var | Recommended Setup |
| :---: | :--- | :--- | :---: | :--- | :--- |
| **1** | **Ollama** | `http://127.0.0.1:11434/v1` | Yes | `null` | `ollama pull qwen2.5-coder:14b` |
| **2** | **LM Studio** | `http://127.0.0.1:1234/v1` | Yes | `null` | Start local server in LM Studio (`1234`) |
| **3** | **OmniRoute** | `http://127.0.0.1:20128/v1` | No (routes out) | `OMNIROUTE_API_KEY` | `npx omniroute` + configure official free tiers |
| **4** | **FreeLLMAPI** | `http://127.0.0.1:3001/v1` | No (routes out) | `FREELLMAPI_API_KEY` | Self-host `tashfeenahmed/freellmapi` |

Check live reachability at any time:
```bash
python scripts/fgh.py ext health
```

---

## 3. Hard Safety, Privacy & Provider Policy

1. **Sanctioned Providers Only**:
   - Inside OmniRoute or FreeLLMAPI, configure **only** official provider free tiers (e.g., Google AI Studio, Groq, Mistral, NVIDIA NIM, OpenRouter free models) using your own legitimate API keys, or local weights on Ollama / LM Studio.
   - **Never** enable reverse-engineered web-session proxies, cookie scrapers, leaked/shared key pools, or subscription-OAuth-to-API bridges. They violate provider Terms of Service, risk account bans, and suffer severe quality variance.
2. **Automatic Secret Scrubbing**:
   - When `external.privacy` is `"scrub"` (default) or `"local_only"`, `fgh.py` automatically redacts AWS keys, GitHub PATs (`ghp_`, `github_pat_`), OpenAI/Anthropic keys (`sk-`), Google API keys (`AIza`), Slack tokens (`xox...`), PEM private keys, JWTs, URL credentials, and `PASSWORD`/`SECRET`/`TOKEN`/`API_KEY` assignments before any request is sent.
3. **Local-Only Mode for Proprietary Repos**:
   - Set `"privacy": "local_only"` (or `"allow_remote": false`) in `.agents/fgh.config.json` to restrict `fgh.py ext` strictly to `local: true` gateways (`ollama`, `lmstudio`).
4. **Automatic Quality Demotion Ledger**:
   - `fgh.py ledger` tracks rolling pass rates over the last `window` (`10`) runs per gateway. Any gateway with `>= 5` runs and `< 70%` pass rate is automatically marked `"demoted": true` and skipped by `select_gateway`.
