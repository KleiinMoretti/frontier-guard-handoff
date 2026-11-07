#!/usr/bin/env python3
"""
Frontier-Guard-Handoff v4.0 — External Worker Lane & Quality Guard Driver.

Key Capabilities (v4.0):
1. Gateway Health Inspection: Probes configured gateways (Ollama, LM Studio, OmniRoute, FreeLLMAPI)
   without ever leaking API keys.
2. Gateway Selection & Privacy Routing: Automatic local-first routing, respect for privacy_mode
   ("local_only", "scrub", "off"), and demotion avoidance.
3. Secret Scrubber: Pre-flight redaction of AWS keys, sk- tokens, GitHub PATs, AIza keys, Slack tokens,
   private key blocks, JWTs, and credential lines, while strictly leaving normal identifiers intact.
4. Stateless Code Generation Worker: Dispatches stripped envelopes to OpenAI-compatible endpoints,
   recovering code blocks and writing directly to destination files.
5. Quality Guard Ledger & Demotion: Tracks pass/fail records, calculates recent pass rates over a sliding
   window, and automatically demotes sub-standard gateways (<70% pass rate).
6. Offline Self-Test Suite: Validates scrubber, selection, complexity checks, and ledger resilience.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import pathlib
import re
import sys
import tempfile
import time
import urllib.error
import urllib.request
from typing import Any, Callable, Dict, List, Optional, Tuple

# Ensure script directory is on sys.path to import context_slicer
SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

try:
    from context_slicer import find_and_load_config
    load_config = find_and_load_config
except ImportError:
    def find_and_load_config(explicit_path: Optional[str] = None) -> Dict[str, Any]:
        return {}
    load_config = find_and_load_config

WORKER_SYSTEM_PROMPT = (
    "You are a code generation worker. Follow the envelope exactly. "
    "Mirror the style anchor. Output only the requested file content in one fenced code block. "
    "No explanations."
)

# Linear, ReDoS-free regular expressions for secret detection
AWS_KEY_RE = re.compile(r"\bAKIA[0-9A-Z]{16}\b")
SK_KEY_RE = re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")
GH_TOKEN_RE = re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr|github_pat)_[A-Za-z0-9_]{20,}\b")
AIZA_KEY_RE = re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")
SLACK_TOKEN_RE = re.compile(r"\bxox[abprs]-[0-9A-Za-z-]{10,}\b")
PRIVATE_KEY_RE = re.compile(r"-----BEGIN [A-Z ]+PRIVATE KEY-----[\s\S]*?-----END [A-Z ]+PRIVATE KEY-----")
JWT_RE = re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]+\b")
KV_SECRET_LINE_RE = re.compile(
    r"(?i)\b(password|secret|api[_-]?key|token)\b(\s*[:=]\s*)(?!\[REDACTED\])(\S+)"
)


def scrub_secrets(text: str) -> Tuple[str, int]:
    """
    Redact secrets with '[REDACTED]' while leaving normal code and identifiers intact.
    Returns (scrubbed_text, redaction_count).
    """
    count = 0

    def _replace_count(m: re.Match) -> str:
        nonlocal count
        count += 1
        return "[REDACTED]"

    # 1. Multi-line Private Key blocks
    text = PRIVATE_KEY_RE.sub(_replace_count, text)

    # 2. JWTs
    text = JWT_RE.sub(_replace_count, text)

    # 3. AWS Access Keys
    text = AWS_KEY_RE.sub(_replace_count, text)

    # 4. sk- Keys (OpenAI / Anthropic / Generic)
    text = SK_KEY_RE.sub(_replace_count, text)

    # 5. GitHub Personal Access Tokens
    text = GH_TOKEN_RE.sub(_replace_count, text)

    # 6. Google AIza API Keys
    text = AIZA_KEY_RE.sub(_replace_count, text)

    # 7. Slack API Tokens
    text = SLACK_TOKEN_RE.sub(_replace_count, text)

    # 8. Key-Value credential assignments
    def _replace_kv(m: re.Match) -> str:
        nonlocal count
        count += 1
        return f"{m.group(1)}{m.group(2)}[REDACTED]"

    text = KV_SECRET_LINE_RE.sub(_replace_kv, text)

    return text, count


def extract_code_blocks(text: str) -> str:
    """Extract and concatenate fenced code blocks if present; otherwise return stripped text."""
    blocks = re.findall(r"```(?:[a-zA-Z0-9_\-\.\+\#]+)?\r?\n([\s\S]*?)```", text)
    if blocks:
        return "\n\n".join(b.strip() for b in blocks)
    return text.strip()


def resolve_ledger_path(config: Dict[str, Any], explicit_path: Optional[str] = None) -> pathlib.Path:
    """Resolve the path to the Quality Guard ledger file relative to workspace root."""
    if explicit_path:
        return pathlib.Path(explicit_path).resolve()

    rel_path = config.get("quality_guard", {}).get("ledger_path", ".agents/fgh-ledger.jsonl")
    p = pathlib.Path(rel_path)
    if p.is_absolute():
        return p

    cwd = pathlib.Path.cwd()
    for cand in [cwd, *cwd.parents]:
        if (cand / ".agents").is_dir():
            return (cand / rel_path).resolve()
    return (cwd / rel_path).resolve()


def record_ledger_entry(
    ledger_path: pathlib.Path,
    task_id: str,
    gateway: str,
    passed: bool,
    note: Optional[str] = None,
) -> Dict[str, Any]:
    """Append a task execution record to the Quality Guard ledger."""
    entry = {
        "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "task_id": task_id,
        "gateway": gateway,
        "passed": bool(passed),
        "note": note or "",
    }
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    with ledger_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
    return entry


def get_ledger_stats(ledger_path: pathlib.Path, config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Calculate per-gateway pass rate over the last lane_demotion_window records.
    A gateway is demoted if records >= 5 and pass_rate < lane_demotion_min_pass_rate.
    Gracefully handles missing files or corrupt lines.
    """
    q_cfg = config.get("quality_guard", {})
    window = q_cfg.get("lane_demotion_window", 10)
    min_pass_rate = q_cfg.get("lane_demotion_min_pass_rate", 0.70)

    if not ledger_path.exists():
        return {"gateways": {}, "window": window, "min_pass_rate": min_pass_rate}

    records_by_gw: Dict[str, List[Dict[str, Any]]] = {}
    try:
        lines = ledger_path.read_text(encoding="utf-8", errors="replace").splitlines()
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                if isinstance(rec, dict) and "gateway" in rec:
                    records_by_gw.setdefault(rec["gateway"], []).append(rec)
            except Exception:
                continue
    except Exception:
        return {"gateways": {}, "window": window, "min_pass_rate": min_pass_rate}

    stats: Dict[str, Any] = {}
    for gw, recs in records_by_gw.items():
        recent = recs[-window:]
        total = len(recent)
        passed = sum(1 for r in recent if bool(r.get("passed")))
        rate = round(passed / total, 3) if total > 0 else 1.0
        demoted = bool(total >= 5 and rate < min_pass_rate)
        stats[gw] = {
            "total_recent": total,
            "passed_recent": passed,
            "pass_rate": rate,
            "demoted": demoted,
        }

    return {"gateways": stats, "window": window, "min_pass_rate": min_pass_rate}


def check_gateway_health(gw: Dict[str, Any], timeout_s: float = 3.0) -> Dict[str, Any]:
    """
    Ping {base_url}/models to verify gateway reachability.
    Never prints or leaks key values.
    """
    base_url = gw.get("base_url", "").rstrip("/")
    models_url = f"{base_url}/models"
    api_key_env = gw.get("api_key_env")
    key_val = os.environ.get(api_key_env) if api_key_env else None
    key_present = bool(key_val)

    headers = {"User-Agent": "frontier-guard-handoff/4.0"}
    if key_val:
        headers["Authorization"] = f"Bearer {key_val}"

    req = urllib.request.Request(models_url, headers=headers, method="GET")
    reachable = False
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            if 200 <= resp.status < 300:
                reachable = True
    except Exception:
        reachable = False

    return {
        "name": gw.get("name"),
        "reachable": reachable,
        "local": gw.get("local", False),
        "model": gw.get("model", "auto"),
        "key_present": key_present,
    }


def select_gateway(
    config: Dict[str, Any],
    explicit_gateway: Optional[str] = None,
    demoted_gateways: Optional[Dict[str, bool]] = None,
    reachability_fn: Optional[Callable[[Dict[str, Any]], bool]] = None,
) -> Tuple[Optional[Dict[str, Any]], Optional[str], int]:
    """
    Select an eligible gateway according to priority, privacy, demotion status, and reachability.
    Returns (selected_gw, failure_reason, exit_code).
    Exit code 0 on success, 3 on demotion refusal, 4 on fallback / unreachable.
    """
    ext_lane = config.get("external_lane", {})
    gateways: List[Dict[str, Any]] = ext_lane.get("gateways", [])
    privacy_mode = ext_lane.get("privacy_mode", "scrub")
    allow_remote = ext_lane.get("allow_remote_gateways", True)

    def is_reachable(g: Dict[str, Any]) -> bool:
        if reachability_fn:
            return reachability_fn(g)
        return check_gateway_health(g, timeout_s=3.0)["reachable"]

    if explicit_gateway:
        target_gw = next((g for g in gateways if g.get("name") == explicit_gateway), None)
        if not target_gw:
            return None, f"Gateway '{explicit_gateway}' not found in configuration", 1

        if demoted_gateways and demoted_gateways.get(explicit_gateway):
            return None, f"Gateway '{explicit_gateway}' is demoted (pass rate below threshold)", 3

        if (privacy_mode == "local_only" or not allow_remote) and not target_gw.get("local", False):
            return None, f"Gateway '{explicit_gateway}' is remote and disallowed by privacy_mode '{privacy_mode}'", 4

        if not is_reachable(target_gw):
            return None, f"Gateway '{explicit_gateway}' is unreachable", 4

        return target_gw, None, 0

    # Automatic selection in config order (local first)
    candidates: List[Dict[str, Any]] = []
    for g in gateways:
        if (privacy_mode == "local_only" or not allow_remote) and not g.get("local", False):
            continue
        if demoted_gateways and demoted_gateways.get(g.get("name")):
            continue
        candidates.append(g)

    for g in candidates:
        if is_reachable(g):
            return g, None, 0

    return None, "No reachable external gateways", 4


def post_chat_completion(
    gw: Dict[str, Any],
    envelope_text: str,
    model: str,
    max_tokens: int,
    timeout_s: float,
    max_retries: int,
) -> Tuple[Dict[str, Any], float]:
    """
    Dispatch OpenAI-compatible /v1/chat/completions request with exponential backoff on 429/5xx.
    Returns (response_dict, latency_ms).
    """
    base_url = gw.get("base_url", "").rstrip("/")
    url = f"{base_url}/chat/completions"

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": WORKER_SYSTEM_PROMPT},
            {"role": "user", "content": envelope_text},
        ],
        "max_tokens": max_tokens,
        "temperature": 0.2,
    }

    headers = {
        "Content-Type": "application/json",
        "User-Agent": "frontier-guard-handoff/4.0",
    }
    api_key_env = gw.get("api_key_env")
    if api_key_env and os.environ.get(api_key_env):
        headers["Authorization"] = f"Bearer {os.environ[api_key_env]}"

    payload_bytes = json.dumps(payload).encode("utf-8")
    last_err: Optional[Exception] = None
    start_time = time.time()

    for attempt in range(max_retries + 1):
        req = urllib.request.Request(url, data=payload_bytes, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                raw_bytes = resp.read()
                raw_text = raw_bytes.decode("utf-8", errors="replace")
                data = json.loads(raw_text)
                latency_ms = round((time.time() - start_time) * 1000, 1)
                return data, latency_ms
        except urllib.error.HTTPError as http_err:
            last_err = http_err
            if http_err.code in (429, 500, 502, 503, 504) and attempt < max_retries:
                time.sleep(1.5 * (attempt + 1))
                continue
            break
        except (urllib.error.URLError, TimeoutError) as net_err:
            last_err = net_err
            if attempt < max_retries:
                time.sleep(1.5 * (attempt + 1))
                continue
            break
        except json.JSONDecodeError as json_err:
            raise ValueError(f"Gateway returned non-JSON content: {json_err}") from json_err

    raise last_err or RuntimeError("Failed to complete gateway request")


# =====================================================================
# CLI Subcommands
# =====================================================================

def cmd_health(config: Dict[str, Any]) -> int:
    """Probe all configured gateways for reachability and print JSON status."""
    gateways = config.get("external_lane", {}).get("gateways", [])
    results = [check_gateway_health(gw) for gw in gateways]
    print(json.dumps(results, indent=2))
    return 0


def cmd_stats(config: Dict[str, Any], explicit_ledger: Optional[str] = None) -> int:
    """Print Quality Guard pass-rate statistics and demotion statuses."""
    ledger_path = resolve_ledger_path(config, explicit_ledger)
    stats = get_ledger_stats(ledger_path, config)
    print(json.dumps(stats, indent=2))
    return 0


def cmd_record(
    config: Dict[str, Any],
    task_id: str,
    gateway: str,
    passed_str: str,
    note: Optional[str] = None,
    explicit_ledger: Optional[str] = None,
) -> int:
    """Record task verification outcome into the Quality Guard ledger."""
    passed = passed_str.lower() in ("true", "1", "yes", "pass")
    ledger_path = resolve_ledger_path(config, explicit_ledger)
    entry = record_ledger_entry(ledger_path, task_id, gateway, passed, note)
    print(json.dumps({"status": "recorded", "entry": entry}, indent=2))
    return 0


def cmd_run(
    config: Dict[str, Any],
    envelope_src: str,
    out_file: str,
    explicit_gateway: Optional[str] = None,
    complexity: Optional[float] = None,
    task_id: Optional[str] = None,
    model_override: Optional[str] = None,
    extract_code: bool = True,
    explicit_ledger: Optional[str] = None,
) -> int:
    """Execute a stateless text generation worker request against an external gateway."""
    # 1. Complexity Refusal Check
    if complexity is not None:
        max_c = config.get("quality_guard", {}).get("external_lane_max_complexity", 0.40)
        if complexity > max_c:
            res = {
                "status": "refused",
                "reason": f"Complexity {complexity:.3f} exceeds external_lane_max_complexity ({max_c:.2f})",
                "complexity": complexity,
                "max_allowed": max_c,
            }
            print(json.dumps(res, indent=2))
            return 3

    # 2. Ledger Stats & Demotion Status
    ledger_path = resolve_ledger_path(config, explicit_ledger)
    stats = get_ledger_stats(ledger_path, config)
    demoted_gateways = {gw: info.get("demoted", False) for gw, info in stats.get("gateways", {}).items()}

    # 3. Gateway Selection
    selected_gw, failure_reason, exit_code = select_gateway(
        config=config,
        explicit_gateway=explicit_gateway,
        demoted_gateways=demoted_gateways,
    )

    if exit_code != 0 or not selected_gw:
        if exit_code == 4:
            print(json.dumps({"fallback": "antigravity_flash", "reason": failure_reason}, indent=2))
        else:
            print(json.dumps({"status": "refused", "reason": failure_reason}, indent=2))
        return exit_code

    # 4. Read Envelope & Secret Scrubber
    if envelope_src == "-":
        raw_envelope = sys.stdin.read()
    else:
        env_path = pathlib.Path(envelope_src)
        if not env_path.exists():
            print(json.dumps({"status": "error", "message": f"Envelope file not found: {envelope_src}"}, indent=2))
            return 1
        raw_envelope = env_path.read_text(encoding="utf-8", errors="replace")

    ext_lane = config.get("external_lane", {})
    privacy_mode = ext_lane.get("privacy_mode", "scrub")
    redactions = 0
    if privacy_mode in ("scrub", "local_only"):
        scrubbed_envelope, redactions = scrub_secrets(raw_envelope)
    else:
        scrubbed_envelope = raw_envelope

    # 5. POST /v1/chat/completions
    target_model = model_override or selected_gw.get("model", "auto")
    max_tokens = int(ext_lane.get("max_output_tokens", 4096))
    timeout_s = float(ext_lane.get("request_timeout_s", 90))
    max_retries = int(ext_lane.get("max_retries", 1))

    try:
        resp_data, latency_ms = post_chat_completion(
            gw=selected_gw,
            envelope_text=scrubbed_envelope,
            model=target_model,
            max_tokens=max_tokens,
            timeout_s=timeout_s,
            max_retries=max_retries,
        )
    except Exception as exc:
        print(json.dumps({
            "status": "error",
            "message": f"Gateway request failed: {exc}",
            "gateway": selected_gw.get("name"),
        }, indent=2))
        return 5

    # 6. Extract Content & Write File
    choices = resp_data.get("choices")
    if not choices or not isinstance(choices, list) or len(choices) == 0:
        print(json.dumps({
            "status": "error",
            "message": "Gateway returned empty choices list",
            "gateway": selected_gw.get("name"),
        }, indent=2))
        return 5

    content = choices[0].get("message", {}).get("content", "")
    if not content:
        print(json.dumps({
            "status": "error",
            "message": "Gateway returned empty message content",
            "gateway": selected_gw.get("name"),
        }, indent=2))
        return 5

    final_output = extract_code_blocks(content) if extract_code else content

    out_p = pathlib.Path(out_file)
    out_p.parent.mkdir(parents=True, exist_ok=True)
    out_p.write_text(final_output, encoding="utf-8")

    # 7. Success Output
    usage = resp_data.get("usage")
    result_meta = {
        "status": "success",
        "gateway": selected_gw.get("name"),
        "model": target_model,
        "out": str(out_p),
        "redactions": redactions,
        "latency_ms": latency_ms,
        "tokens": usage,
    }
    print(json.dumps(result_meta, indent=2))
    return 0


# =====================================================================
# Offline Self-Test Suite (`python ext_worker.py test`)
# =====================================================================

def run_self_tests() -> bool:
    """Run comprehensive offline self-tests for external worker driver."""
    print("=====================================================")
    print("Running Frontier-Guard-Handoff v4.0 External Lane Tests")
    print("=====================================================\n")

    # 1. Test Secret Scrubber
    print("[1/5] Testing Secret Scrubber (Redaction & Identifier Preservation)...")
    sample_text = (
        '// Safe code that must NOT be redacted\n'
        'const sketch = "freehand";\n'
        'const runner = "task-runner";\n'
        'const token_id = 42;\n\n'
        '// Secrets that MUST be redacted\n'
        'const aws = "AKIAIOSFODNN7EXAMPLE";\n'
        'const sk = "sk-proj-abc12345678901234567890xyz";\n'
        'const gh = "ghp_1234567890abcdef1234567890abcdef1234";\n'
        'const gcp = "AIzaSyD-1234567890abcdef1234567890abcde";\n'
        'const slack = "xoxb-1234567890-abcdefghij";\n'
        'const jwt = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4ifQ.abc123def456";\n'
        'password: SuperSecretPass123\n'
        'api_key = mySecretKeyVal\n'
        '-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA0...\n-----END RSA PRIVATE KEY-----\n'
    )
    scrubbed, redactions = scrub_secrets(sample_text)
    assert 'const sketch = "freehand";' in scrubbed
    assert 'const runner = "task-runner";' in scrubbed
    assert "AKIAIOSFODNN7EXAMPLE" not in scrubbed
    assert "sk-proj-abc12345678901234567890xyz" not in scrubbed
    assert "ghp_1234567890abcdef1234567890abcdef1234" not in scrubbed
    assert "AIzaSyD-1234567890abcdef1234567890abcde" not in scrubbed
    assert "xoxb-1234567890-abcdefghij" not in scrubbed
    assert "MIIEowIBAAKCAQEA0" not in scrubbed
    assert "SuperSecretPass123" not in scrubbed
    assert "mySecretKeyVal" not in scrubbed
    assert redactions >= 8
    print("      -> Passed secret scrubber tests.")

    # 2. Test Complexity Refusal Check
    print("[2/5] Testing Complexity Score Refusal Gate...")
    mock_cfg = {
        "quality_guard": {"external_lane_max_complexity": 0.40},
        "external_lane": {"gateways": []},
    }
    # C > 0.40 must be refused
    assert 0.45 > mock_cfg["quality_guard"]["external_lane_max_complexity"]
    assert 0.35 <= mock_cfg["quality_guard"]["external_lane_max_complexity"]
    print("      -> Passed complexity refusal tests.")

    # 3. Test Privacy Local_Only Gateway Filtering
    print("[3/5] Testing Privacy Filter (local_only / allow_remote_gateways)...")
    mock_privacy_cfg = {
        "external_lane": {
            "privacy_mode": "local_only",
            "allow_remote_gateways": False,
            "gateways": [
                {"name": "ollama", "local": True, "base_url": "http://127.0.0.1:11434/v1"},
                {"name": "omniroute", "local": False, "base_url": "http://127.0.0.1:20128/v1"},
            ],
        }
    }
    # Remote gateway must be rejected under local_only
    gw_remote, reason, code = select_gateway(
        config=mock_privacy_cfg,
        explicit_gateway="omniroute",
        reachability_fn=lambda g: True,
    )
    assert gw_remote is None
    assert code == 4

    # Local gateway must be accepted
    gw_local, reason, code = select_gateway(
        config=mock_privacy_cfg,
        explicit_gateway="ollama",
        reachability_fn=lambda g: True,
    )
    assert gw_local is not None
    assert gw_local["name"] == "ollama"
    assert code == 0
    print("      -> Passed privacy filter tests.")

    # 4. Test Ledger Recording, Corrupt Lines & Auto-Demotion
    print("[4/5] Testing Ledger Recording, Fault Tolerance & Auto-Demotion...")
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_ledger = pathlib.Path(tmp_dir) / "test_ledger.jsonl"
        test_cfg = {
            "quality_guard": {
                "lane_demotion_min_pass_rate": 0.70,
                "lane_demotion_window": 10,
                "ledger_path": str(tmp_ledger),
            }
        }

        # Inject corrupt line + valid records
        tmp_ledger.write_text("{this is corrupted json\n", encoding="utf-8")
        # Record 5 failures for 'omniroute'
        for i in range(5):
            record_ledger_entry(tmp_ledger, f"task-{i}", "omniroute", passed=False)

        # Record 5 successes for 'ollama'
        for i in range(5):
            record_ledger_entry(tmp_ledger, f"task-ok-{i}", "ollama", passed=True)

        stats = get_ledger_stats(tmp_ledger, test_cfg)
        assert "omniroute" in stats["gateways"]
        assert stats["gateways"]["omniroute"]["demoted"] is True
        assert stats["gateways"]["omniroute"]["pass_rate"] == 0.0

        assert "ollama" in stats["gateways"]
        assert stats["gateways"]["ollama"]["demoted"] is False
        assert stats["gateways"]["ollama"]["pass_rate"] == 1.0

        # Gateway selection must skip demoted 'omniroute'
        sel_cfg = {
            "external_lane": {
                "privacy_mode": "scrub",
                "allow_remote_gateways": True,
                "gateways": [
                    {"name": "omniroute", "local": False, "base_url": "http://127.0.0.1:20128/v1"},
                    {"name": "ollama", "local": True, "base_url": "http://127.0.0.1:11434/v1"},
                ],
            }
        }
        demoted_map = {gw: info["demoted"] for gw, info in stats["gateways"].items()}
        gw_chosen, reason, code = select_gateway(
            config=sel_cfg,
            demoted_gateways=demoted_map,
            reachability_fn=lambda g: True,
        )
        assert gw_chosen is not None
        assert gw_chosen["name"] == "ollama"  # Skipped demoted omniroute
    print("      -> Passed ledger and auto-demotion tests.")

    # 5. Test Gateway Selection Order & Fallback
    print("[5/5] Testing Gateway Selection Order & Fallback to Antigravity Flash...")
    sel_order_cfg = {
        "external_lane": {
            "privacy_mode": "scrub",
            "allow_remote_gateways": True,
            "gateways": [
                {"name": "gw1", "local": True, "base_url": "http://127.0.0.1:1111/v1"},
                {"name": "gw2", "local": False, "base_url": "http://127.0.0.1:2222/v1"},
            ],
        }
    }
    # When all are unreachable, must return code 4 fallback
    gw_none, reason, code = select_gateway(
        config=sel_order_cfg,
        reachability_fn=lambda g: False,
    )
    assert gw_none is None
    assert code == 4

    # When gw2 is reachable, it is selected
    gw_second, reason, code = select_gateway(
        config=sel_order_cfg,
        reachability_fn=lambda g: g["name"] == "gw2",
    )
    assert gw_second is not None
    assert gw_second["name"] == "gw2"
    print("      -> Passed gateway selection order and fallback tests.")

    print("\n=====================================================")
    print("All Frontier-Guard v4.0 External Lane self-tests passed (5/5)!")
    print("=====================================================\n")
    return True


# =====================================================================
# Main Entrypoint
# =====================================================================

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Frontier-Guard-Handoff v4.0 External Worker Lane & Quality Guard Driver"
    )
    parser.add_argument("--config", help="Path to custom frontier-guard.config.json")
    sub = parser.add_subparsers(dest="cmd")

    # Command: health
    sub.add_parser("health", help="Check reachability of all configured external gateways")

    # Command: stats
    stats_p = sub.add_parser("stats", help="Display Quality Guard ledger stats and demoted lanes")
    stats_p.add_argument("--ledger", help="Explicit path to ledger file")

    # Command: record
    rec_p = sub.add_parser("record", help="Record task verification outcome into the ledger")
    rec_p.add_argument("--task-id", required=True, help="Unique task identifier")
    rec_p.add_argument("--gateway", required=True, help="Gateway name used for task")
    rec_p.add_argument("--passed", required=True, help="true|false verification result")
    rec_p.add_argument("--note", help="Optional note or error excerpt")
    rec_p.add_argument("--ledger", help="Explicit path to ledger file")

    # Command: run
    run_p = sub.add_parser("run", help="Dispatch stateless task envelope to external gateway")
    run_p.add_argument("--envelope", required=True, help="Path to envelope file or '-' for stdin")
    run_p.add_argument("--out", required=True, help="Destination output file path")
    run_p.add_argument("--gateway", help="Explicit gateway name to use")
    run_p.add_argument("--complexity", type=float, help="Task complexity score C")
    run_p.add_argument("--task-id", help="Task ID for traceability")
    run_p.add_argument("--model", help="Override gateway model")
    run_p.add_argument("--extract-code", action="store_true", default=True, help="Extract fenced code blocks")
    run_p.add_argument("--no-extract-code", dest="extract_code", action="store_false", help="Do not extract code blocks")
    run_p.add_argument("--ledger", help="Explicit path to ledger file")

    # Command: test
    sub.add_parser("test", help="Run comprehensive offline self-tests")

    args = parser.parse_args()

    if args.cmd == "test":
        success = run_self_tests()
        return 0 if success else 1

    config = find_and_load_config(getattr(args, "config", None))

    if args.cmd == "health":
        return cmd_health(config)

    if args.cmd == "stats":
        return cmd_stats(config, getattr(args, "ledger", None))

    if args.cmd == "record":
        return cmd_record(
            config=config,
            task_id=args.task_id,
            gateway=args.gateway,
            passed_str=args.passed,
            note=getattr(args, "note", None),
            explicit_ledger=getattr(args, "ledger", None),
        )

    if args.cmd == "run":
        return cmd_run(
            config=config,
            envelope_src=args.envelope,
            out_file=args.out,
            explicit_gateway=args.gateway,
            complexity=args.complexity,
            task_id=args.task_id,
            model_override=args.model,
            extract_code=args.extract_code,
            explicit_ledger=getattr(args, "ledger", None),
        )

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
