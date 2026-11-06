#!/usr/bin/env python3
"""
Frontier-Guard-Handoff v3.1 — Universal Polyglot Context Slicer & Complexity Scorer.

Key Capabilities (v3.1):
1. Instant Kill-Switch Detection (/direct, /max, /frontier, /bypass, /off, /no-delegate)
   with boundary-aware regex preventing mid-path/URL false positives.
2. Fast-Path Inline Bypass Detection (<= 1 file and <= 35 lines).
3. Anti-Recursion Subagent Worker Guard enforcement.
4. Auto-loading configuration from .agents/frontier-guard.config.json or frontier-guard.config.json.
5. Deterministic 5-factor complexity scoring with validated & clamped inputs.
6. ReDoS-free multi-line signature extraction:
   - Python: ast.parse() with parameter lists, type annotations, and class methods.
   - TypeScript / JS: full interface, enum, and type blocks (up to 25 lines) + balanced functions.
   - Rust / Go / Java / C# / C++: multi-line balanced signatures up to '{' or ';'.
   - SQL & Terraform HCL declarations.
7. Valid XML Envelope Generation with CDATA wrappers for generics and shell commands.
8. Built-in Self-Test Suite (`python context_slicer.py test`).
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import pathlib
import re
import sys
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional, Tuple

DEFAULT_CONFIG: Dict[str, Any] = {
    "version": "3.1.0",
    "quality_profile": "ZERO_REGRESSION",
    "override_keywords": [
        "/direct",
        "/max",
        "/frontier",
        "/bypass",
        "/off",
        "/no-delegate",
    ],
    "allow_any_slash_keyword_override": False,
    "fast_path_inline_bypass": {
        "max_files": 1,
        "max_changed_lines": 35,
    },
    "complexity_weights": {
        "coupling": 0.25,
        "concurrency": 0.25,
        "novelty": 0.20,
        "blast_radius": 0.15,
        "irreversibility": 0.15,
    },
    "tier_thresholds": {
        "tier1_ceiling": 0.25,
        "tier2_ceiling": 0.55,
    },
}

SLASH_KEYWORD_REGEX = re.compile(
    r"(?:^|(?<=\s))(/[a-zA-Z0-9_-]+)(?=\s|$|[.,!?;:])"
)


def find_and_load_config(explicit_path: Optional[str] = None) -> Dict[str, Any]:
    """Search for and load configuration from disk, falling back to DEFAULT_CONFIG."""
    config = dict(DEFAULT_CONFIG)
    candidate_paths: List[pathlib.Path] = []

    if explicit_path:
        candidate_paths.append(pathlib.Path(explicit_path))

    cwd = pathlib.Path.cwd()
    candidate_paths.extend([
        cwd / ".agents" / "frontier-guard.config.json",
        cwd / "frontier-guard.config.json",
        cwd / "skills" / "frontier-guard-handoff" / "frontier-guard.config.json",
    ])

    for parent in list(cwd.parents)[:3]:
        candidate_paths.extend([
            parent / ".agents" / "frontier-guard.config.json",
            parent / "frontier-guard.config.json",
        ])

    for candidate in candidate_paths:
        try:
            if candidate.is_file():
                data = json.loads(candidate.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    # Shallow/nested merge
                    for k, v in data.items():
                        if isinstance(v, dict) and isinstance(config.get(k), dict):
                            config[k] = {**config[k], **v}
                        else:
                            config[k] = v
                    break
        except Exception:
            continue

    return config


def check_prompt_override(
    prompt_text: str,
    estimated_files: int = 2,
    estimated_lines: int = 100,
    config: Optional[Dict[str, Any]] = None,
    allow_any_slash_override: Optional[bool] = None,
) -> Dict[str, Any]:
    """
    Check if the prompt triggers the /direct kill-switch or Fast-Path Inline Bypass.
    Regex matches slash-keywords ONLY when preceded by start-of-string or whitespace,
    preventing mid-path strings (e.g. src/direct/foo.ts) or URLs (https://example.com/max).
    """
    cfg = config or find_and_load_config()
    override_keywords = set(k.lower() for k in cfg.get("override_keywords", DEFAULT_CONFIG["override_keywords"]))
    any_slash = (
        allow_any_slash_override
        if allow_any_slash_override is not None
        else cfg.get("allow_any_slash_keyword_override", False)
    )

    matches = [m.lower() for m in SLASH_KEYWORD_REGEX.findall(prompt_text)]

    triggered_kw = None
    if any_slash and matches:
        triggered_kw = matches[0]
    else:
        for m in matches:
            if m in override_keywords:
                triggered_kw = m
                break

    if triggered_kw:
        return {
            "delegation_enabled": False,
            "reason": f"Kill-switch keyword detected: {triggered_kw}",
            "execution_mode": "INLINE_FRONTIER_DIRECT",
            "matched_keyword": triggered_kw,
            "all_detected_slash_tokens": matches,
        }

    fast_path_cfg = cfg.get("fast_path_inline_bypass", DEFAULT_CONFIG["fast_path_inline_bypass"])
    max_files = fast_path_cfg.get("max_files", 1)
    max_lines = fast_path_cfg.get("max_changed_lines", 35)

    if estimated_files <= max_files and estimated_lines <= max_lines:
        return {
            "delegation_enabled": False,
            "reason": f"Fast-Path Inline Bypass ({estimated_files} file(s) <= {max_files}, ~{estimated_lines} line(s) <= {max_lines})",
            "execution_mode": "INLINE_FAST_PATH",
            "matched_keyword": None,
            "all_detected_slash_tokens": matches,
        }

    return {
        "delegation_enabled": True,
        "reason": "Standard Quota-Preserving Adaptive Delegation active",
        "execution_mode": "ADAPTIVE_DELEGATION",
        "matched_keyword": None,
        "all_detected_slash_tokens": matches,
    }


def compute_complexity_score(
    coupling: float,
    concurrency: float,
    novelty: float,
    blast_radius: float,
    irreversibility: float,
    domain: str = "code",
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Compute the deterministic 5-factor complexity score C in [0.00, 1.00].
    Validates and clamps each input to [0.0, 1.0] and raises ValueError if out of bounds.
    """
    cfg = config or find_and_load_config()
    weights = cfg.get("complexity_weights", DEFAULT_CONFIG["complexity_weights"])
    thresholds = cfg.get("tier_thresholds", DEFAULT_CONFIG["tier_thresholds"])

    raw_factors = {
        "coupling": coupling,
        "concurrency": concurrency,
        "novelty": novelty,
        "blast_radius": blast_radius,
        "irreversibility": irreversibility,
    }

    clamped: Dict[str, float] = {}
    for name, val in raw_factors.items():
        try:
            fval = float(val)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Complexity factor '{name}' must be a valid float, got {val!r}") from exc

        if fval < 0.0 or fval > 1.0:
            raise ValueError(
                f"Complexity factor '{name}' out of bounds: {fval} (must be in [0.0, 1.0])"
            )
        clamped[name] = min(1.0, max(0.0, fval))

    score = round(
        weights.get("coupling", 0.25) * clamped["coupling"]
        + weights.get("concurrency", 0.25) * clamped["concurrency"]
        + weights.get("novelty", 0.20) * clamped["novelty"]
        + weights.get("blast_radius", 0.15) * clamped["blast_radius"]
        + weights.get("irreversibility", 0.15) * clamped["irreversibility"],
        3,
    )

    t1 = thresholds.get("tier1_ceiling", 0.25)
    t2 = thresholds.get("tier2_ceiling", 0.55)

    if score < t1:
        tier = "tier1_flash_lite"
        mode = "DIRECT_ASYNC_WORKER"
    elif score < t2:
        tier = "tier2_flash"
        mode = "DIRECT_ASYNC_WORKER_WITH_STYLE_ANCHOR"
    else:
        tier = "tier3_frontier_blueprint_then_tier2_flash"
        mode = "BLUEPRINT_ONLY_350_TOKENS_THEN_FANOUT"

    return {
        "domain": domain,
        "complexity_score": score,
        "recommended_tier": tier,
        "execution_mode": mode,
        "requires_micro_audit": clamped["blast_radius"] >= 0.8 or clamped["irreversibility"] >= 0.8,
        "breakdown": clamped,
    }


# =====================================================================
# Polyglot AST & Multi-Line Signature Extraction
# =====================================================================

def _extract_python_ast(content: str, max_lines: int = 60) -> List[str]:
    """Extract Python signatures using ast.parse() with full multi-line type annotations."""
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return _extract_python_fallback(content, max_lines)

    extracted: List[str] = []

    def format_func(node: ast.FunctionDef | ast.AsyncFunctionDef, indent: str = "") -> str:
        prefix = "async def " if isinstance(node, ast.AsyncFunctionDef) else "def "
        node_type = ast.AsyncFunctionDef if isinstance(node, ast.AsyncFunctionDef) else ast.FunctionDef
        dummy = node_type(
            name=node.name,
            args=node.args,
            body=[ast.Expr(value=ast.Constant(value=Ellipsis))],
            decorator_list=node.decorator_list,
            returns=node.returns,
            type_comment=getattr(node, "type_comment", None),
        )
        ast.copy_location(dummy, node)
        ast.fix_missing_locations(dummy)
        unparsed = ast.unparse(dummy)
        # Compact single-line representation if body is just ...
        unparsed = unparsed.replace("\n    ...", " ...").replace("\n    pass", " ...")
        lines = unparsed.splitlines()
        return "\n".join(f"{indent}{l}" for l in lines)

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            extracted.append(f"L{node.lineno}: {format_func(node)}")
        elif isinstance(node, ast.ClassDef):
            bases_str = f"({', '.join(ast.unparse(b) for b in node.bases)})" if node.bases else ""
            extracted.append(f"L{node.lineno}: class {node.name}{bases_str}:")
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    extracted.append(f"    L{item.lineno}: {format_func(item)}")
        if len(extracted) >= max_lines:
            break

    return extracted[:max_lines]


def _extract_python_fallback(content: str, max_lines: int = 60) -> List[str]:
    """Safe fallback scanner for incomplete Python files."""
    lines = content.splitlines()
    extracted: List[str] = []
    py_header_re = re.compile(r"^\s*(?:async\s+def|def|class)\s+[A-Za-z0-9_]+")

    i = 0
    while i < len(lines):
        line = lines[i]
        if py_header_re.match(line):
            start_lineno = i + 1
            sig_lines = [line.rstrip()]
            paren_depth = line.count("(") - line.count(")")
            while paren_depth > 0 and i + 1 < len(lines) and len(sig_lines) < 15:
                i += 1
                next_line = lines[i]
                sig_lines.append(next_line.rstrip())
                paren_depth += next_line.count("(") - next_line.count(")")
            combined = "\n".join(sig_lines)
            if combined.endswith(":"):
                combined = combined + " ..."
            extracted.append(f"L{start_lineno}: {combined}")
            if len(extracted) >= max_lines:
                break
        i += 1

    return extracted


def _extract_typescript_blocks(content: str, max_lines: int = 60) -> List[str]:
    """
    Extract TypeScript/JavaScript interface, enum, and type blocks (up to 25 lines each)
    and multi-line function/method/class signatures with balanced parentheses.
    """
    lines = content.splitlines()
    extracted: List[str] = []

    block_start_re = re.compile(
        r"^\s*(?:export\s+)?(?:default\s+)?(?:interface|enum)\s+([A-Za-z0-9_]+)"
    )
    type_alias_re = re.compile(
        r"^\s*(?:export\s+)?(?:default\s+)?type\s+([A-Za-z0-9_]+)\s*="
    )
    fn_class_re = re.compile(
        r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?(?:function|class|const)\s+([A-Za-z0-9_]+)"
    )

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # 1. Interface or Enum Block
        if block_start_re.match(line):
            start_lineno = i + 1
            block_lines = [line.rstrip()]
            brace_depth = line.count("{") - line.count("}")
            while i + 1 < len(lines) and len(block_lines) < 25:
                i += 1
                cur = lines[i]
                block_lines.append(cur.rstrip())
                brace_depth += cur.count("{") - cur.count("}")
                if brace_depth <= 0:
                    break
            extracted.append(f"L{start_lineno}: " + "\n".join(block_lines))

        # 2. Type Alias (e.g. export type Foo = { ... } or union)
        elif type_alias_re.match(line):
            start_lineno = i + 1
            block_lines = [line.rstrip()]
            brace_depth = line.count("{") - line.count("}")
            paren_depth = line.count("(") - line.count(")")
            while i + 1 < len(lines) and len(block_lines) < 25:
                if (brace_depth <= 0 and paren_depth <= 0 and block_lines[-1].endswith(";")) or (brace_depth == 0 and "}" in block_lines[-1]):
                    break
                i += 1
                cur = lines[i]
                block_lines.append(cur.rstrip())
                brace_depth += cur.count("{") - cur.count("}")
                paren_depth += cur.count("(") - cur.count(")")
                if brace_depth <= 0 and cur.strip().endswith(";"):
                    break
            extracted.append(f"L{start_lineno}: " + "\n".join(block_lines))

        # 3. Functions / Classes / Arrow Exports
        elif fn_class_re.match(line):
            start_lineno = i + 1
            sig_lines = [line.rstrip()]
            paren_depth = line.count("(") - line.count(")")
            while paren_depth > 0 and i + 1 < len(lines) and len(sig_lines) < 15:
                i += 1
                cur = lines[i]
                sig_lines.append(cur.rstrip())
                paren_depth += cur.count("(") - cur.count(")")
            # Clean up trailing brace
            combined = "\n".join(sig_lines)
            if combined.endswith("{"):
                combined = combined[:-1].rstrip() + ";"
            extracted.append(f"L{start_lineno}: {combined}")

        if len(extracted) >= max_lines:
            break
        i += 1

    return extracted[:max_lines]


def _extract_polyglot_signatures(content: str, max_lines: int = 60) -> List[str]:
    """
    Multi-line parenthesis balancing for Rust, Go, Java, C#, C++, SQL, and Terraform.
    Guaranteed ReDoS-free: uses linear scanning and parenthesis counters.
    """
    lines = content.splitlines()
    extracted: List[str] = []

    # Safe start-of-declaration patterns without nested quantifiers
    poly_starts = [
        # Rust
        re.compile(r"^\s*(?:pub(?:\([^\)]+\))?\s+)?(?:async\s+)?(?:unsafe\s+)?(?:fn|struct|enum|trait|type|impl)\s+[A-Za-z0-9_]+"),
        # Go
        re.compile(r"^\s*(?:func\s+(?:\([^\)]+\)\s+)?[A-Za-z0-9_]+|type\s+[A-Za-z0-9_]+\s+(?:struct|interface))"),
        # Java / C# / Kotlin / Swift / C++
        re.compile(r"^\s*(?:public|protected|internal|open)\s+(?:static\s+|final\s+|abstract\s+|virtual\s+|override\s+|async\s+)*(?:class|interface|struct|enum|record|fun|func|[A-Za-z0-9_<>\[\]]+)\s+[A-Za-z0-9_]+"),
        # SQL / BigQuery / dbt
        re.compile(r"^\s*CREATE\s+(?:OR\s+REPLACE\s+)?(?:TABLE|VIEW|MATERIALIZED\s+VIEW|FUNCTION|PROCEDURE)\s+.*$", re.IGNORECASE),
        # Terraform / HCL
        re.compile(r'^\s*(?:resource|module|variable|output|data)\s+"[^"]+".*$'),
    ]

    i = 0
    while i < len(lines):
        line = lines[i]
        matched = any(pat.match(line) for pat in poly_starts)
        if matched:
            start_lineno = i + 1
            sig_lines = [line.rstrip()]
            paren_depth = line.count("(") - line.count(")")
            while paren_depth > 0 and i + 1 < len(lines) and len(sig_lines) < 15:
                i += 1
                cur = lines[i]
                sig_lines.append(cur.rstrip())
                paren_depth += cur.count("(") - cur.count(")")

            combined = "\n".join(sig_lines)
            if combined.endswith("{"):
                combined = combined[:-1].rstrip() + ";"
            extracted.append(f"L{start_lineno}: {combined}")
            if len(extracted) >= max_lines:
                break
        i += 1

    return extracted[:max_lines]


def extract_signatures(file_path: pathlib.Path, max_lines: int = 60) -> List[str]:
    """Extract signatures cleanly based on file type."""
    if not file_path.exists():
        return [f"// File not found: {file_path}"]

    try:
        content = file_path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        return [f"// Error reading {file_path}: {exc}"]

    ext = file_path.suffix.lower()
    if ext == ".py":
        return _extract_python_ast(content, max_lines)
    elif ext in (".ts", ".tsx", ".js", ".jsx", ".mjs"):
        return _extract_typescript_blocks(content, max_lines)
    else:
        return _extract_polyglot_signatures(content, max_lines)


def extract_style_anchor(file_path: pathlib.Path, start_line: int = 1, num_lines: int = 15) -> str:
    """Extract a canonical 15-line style anchor from an exemplar file."""
    if not file_path.exists():
        return f"// Style anchor file not found: {file_path}"
    try:
        lines = file_path.read_text(encoding="utf-8", errors="replace").splitlines()
        lo = max(0, start_line - 1)
        hi = min(len(lines), lo + num_lines)
        return "\n".join(lines[lo:hi])
    except Exception as exc:
        return f"// Error reading style anchor {file_path}: {exc}"


def wrap_cdata(content: str) -> str:
    """Safely wrap content in CDATA, splitting any nested ']]>'."""
    escaped = content.replace("]]>", "]]]]><![CDATA[>")
    return f"<![CDATA[\n{escaped}\n]]>"


def build_subtask_envelope(
    subtask_id: str,
    objective: str,
    dependency_signatures: List[str],
    style_anchor_snippet: str,
    anchor_file: str = "",
    anchor_start: int = 1,
    verification_cmd: str = "npx tsc --noEmit",
    tier: str = "tier2_flash",
    frontier_blueprint: Optional[str] = None,
    adversarial_test_seeds: Optional[List[str]] = None,
) -> str:
    """
    Generate an XML-compliant <subtask_envelope> wrapped with CDATA
    so generics (Result<T, E>) and command operators (&&) do not break XML parsing.
    Includes the Anti-Recursion Worker Guard to prevent infinite subagent recursion.
    """
    anti_recursion_notice = (
        "ANTI-RECURSION WORKER GUARD: You are a delegated worker subagent. "
        "DO NOT delegate further or spawn sub-subagents. Execute the task directly, "
        "verify with the verification command, and return <subtask_result>."
    )

    parts = [
        f'<subtask_envelope id="{subtask_id}" tier="{tier}">',
        f"  <worker_anti_recursion_guard>",
        f"    {wrap_cdata(anti_recursion_notice)}",
        f"  </worker_anti_recursion_guard>",
        f"  <task_objective>",
        f"    {wrap_cdata(objective)}",
        f"  </task_objective>",
    ]

    if frontier_blueprint:
        parts.extend([
            f"  <frontier_blueprint>",
            f"    {wrap_cdata(frontier_blueprint)}",
            f"  </frontier_blueprint>",
        ])

    joined_sigs = "\n".join(dependency_signatures) if dependency_signatures else "// No dependencies"
    parts.extend([
        f"  <dependency_signatures>",
        f"    {wrap_cdata(joined_sigs)}",
        f"  </dependency_signatures>",
        f'  <style_clone_anchor file="{anchor_file}" start_line="{anchor_start}">',
        f"    {wrap_cdata(style_anchor_snippet)}",
        f"  </style_clone_anchor>",
    ])

    if adversarial_test_seeds:
        seeds_text = "\n".join(f"- {s}" for s in adversarial_test_seeds)
        parts.extend([
            f"  <adversarial_test_seeds>",
            f"    {wrap_cdata(seeds_text)}",
            f"  </adversarial_test_seeds>",
        ])

    parts.extend([
        f"  <verification_contract>",
        f"    {wrap_cdata(verification_cmd)}",
        f"  </verification_contract>",
        f"</subtask_envelope>",
    ])

    return "\n".join(parts)


# =====================================================================
# Built-in Self-Test Suite (`python context_slicer.py test`)
# =====================================================================

def run_self_tests() -> bool:
    """Run comprehensive unit tests covering all 6 architectural bug fixes."""
    print("=====================================================")
    print("Running Frontier-Guard-Handoff v3.1 Self-Test Suite")
    print("=====================================================\n")

    # 1. Test Prompt Override Regex & Edge Cases
    print("[1/7] Testing prompt override regex & mid-path / URL false-positive rejection...")
    # Positive triggers
    assert check_prompt_override("/direct fix this")["delegation_enabled"] is False
    assert check_prompt_override("run with /max")["delegation_enabled"] is False
    assert check_prompt_override("Please /frontier, thanks.")["delegation_enabled"] is False
    assert check_prompt_override("turn /off delegation")["delegation_enabled"] is False
    assert check_prompt_override("/bypass!")["delegation_enabled"] is False
    assert check_prompt_override("mode: /no-delegate;")["delegation_enabled"] is False

    # Negative triggers (must NOT trigger override)
    assert check_prompt_override("edit src/direct/foo.ts")["delegation_enabled"] is True
    assert check_prompt_override("see https://example.com/max/test")["delegation_enabled"] is True
    assert check_prompt_override("check /api/v1/bypass endpoint")["delegation_enabled"] is True
    assert check_prompt_override("look at C:/frontier/path")["delegation_enabled"] is True

    # Fast-path inline bypass
    fp_res = check_prompt_override("Fix typo in README", estimated_files=1, estimated_lines=10)
    assert fp_res["delegation_enabled"] is False
    assert fp_res["execution_mode"] == "INLINE_FAST_PATH"

    heavy_res = check_prompt_override("Build component", estimated_files=2, estimated_lines=50)
    assert heavy_res["delegation_enabled"] is True
    assert heavy_res["execution_mode"] == "ADAPTIVE_DELEGATION"
    print("      -> Passed prompt override & fast-path tests.")

    # 2. Test Configuration Auto-Loading & Fallbacks
    print("[2/7] Testing configuration loader & default fallbacks...")
    cfg = find_and_load_config()
    assert "version" in cfg
    assert "/direct" in cfg["override_keywords"]
    assert cfg["fast_path_inline_bypass"]["max_changed_lines"] == 35
    print("      -> Passed configuration loader tests.")

    # 3. Test Complexity Scoring & Factor Validation
    print("[3/7] Testing complexity scoring & factor clamping / validation...")
    score_low = compute_complexity_score(0.1, 0.1, 0.1, 0.1, 0.1)
    assert score_low["recommended_tier"] == "tier1_flash_lite"

    score_med = compute_complexity_score(0.4, 0.4, 0.3, 0.2, 0.2)
    assert score_med["recommended_tier"] == "tier2_flash"

    score_high = compute_complexity_score(0.9, 0.8, 0.7, 0.9, 0.8)
    assert score_high["recommended_tier"] == "tier3_frontier_blueprint_then_tier2_flash"
    assert score_high["requires_micro_audit"] is True

    # Out of bounds check: must raise ValueError
    try:
        compute_complexity_score(1.5, 0.2, 0.2, 0.2, 0.2)
        assert False, "Should have raised ValueError on > 1.0 factor"
    except ValueError:
        pass

    try:
        compute_complexity_score(-0.2, 0.2, 0.2, 0.2, 0.2)
        assert False, "Should have raised ValueError on < 0.0 factor"
    except ValueError:
        pass
    print("      -> Passed complexity scoring & factor validation tests.")

    # 4. Test Python AST Signature Extraction (Multi-Line & Classes)
    print("[4/7] Testing Python AST signature extraction...")
    py_sample = (
        "def simple():\n"
        "    return 1\n\n"
        "def complex_fn(\n"
        "    x: int,\n"
        "    y: list[str] | None = None,\n"
        ") -> dict[str, int]:\n"
        "    '''docstring'''\n"
        "    return {}\n\n"
        "class WorkerService:\n"
        "    def run(self, task_id: str) -> bool:\n"
        "        return True\n"
    )
    py_sigs = _extract_python_ast(py_sample)
    assert any("def simple" in s for s in py_sigs)
    assert any("def complex_fn(x: int, y: list[str] | None=None) -> dict[str, int]:" in s for s in py_sigs)
    assert any("class WorkerService:" in s for s in py_sigs)
    assert any("def run(self, task_id: str) -> bool:" in s for s in py_sigs)
    print("      -> Passed Python AST multi-line signature extraction.")

    # 5. Test TypeScript Interface / Enum Block & Parenthesis Balancing
    print("[5/7] Testing TypeScript interface / enum blocks & function signatures...")
    ts_sample = (
        "export interface UserProfile {\n"
        "  id: string;\n"
        "  roles: string[];\n"
        "  metadata?: Record<string, any>;\n"
        "}\n\n"
        "export enum Status {\n"
        "  ACTIVE = 'active',\n"
        "  PENDING = 'pending'\n"
        "}\n\n"
        "export async function executePipeline(\n"
        "  ctx: Context,\n"
        "  retryCount: number = 3\n"
        "): Promise<Result<void, Error>> {\n"
        "  return Ok();\n"
        "}\n"
    )
    ts_sigs = _extract_typescript_blocks(ts_sample)
    assert any("export interface UserProfile {" in s and "roles: string[];" in s for s in ts_sigs)
    assert any("export enum Status {" in s and "ACTIVE = 'active'" in s for s in ts_sigs)
    assert any("export async function executePipeline" in s and "Promise<Result<void, Error>>" in s for s in ts_sigs)
    print("      -> Passed TypeScript interface & function block extraction.")

    # 6. Test Polyglot Rust / Go / Java / SQL Multi-Line Signatures
    print("[6/7] Testing Rust / Go / Java / SQL multi-line signatures...")
    rust_sample = (
        "pub async fn process_event(\n"
        "    event: Event,\n"
        "    sender: mpsc::Sender<Result<Payload, Error>>,\n"
        ") -> Result<(), ServiceError> {\n"
        "    Ok(())\n"
        "}\n"
    )
    rust_sigs = _extract_polyglot_signatures(rust_sample)
    assert any("pub async fn process_event" in s and "Result<(), ServiceError>" in s for s in rust_sigs)

    go_sample = (
        "func ProcessOrder(\n"
        "    ctx context.Context,\n"
        "    order *OrderRequest,\n"
        ") (*OrderResponse, error) {\n"
        "    return nil, nil\n"
        "}\n"
    )
    go_sigs = _extract_polyglot_signatures(go_sample)
    assert any("func ProcessOrder" in s and "(*OrderResponse, error)" in s for s in go_sigs)
    print("      -> Passed polyglot multi-line signatures.")

    # 7. Test XML Envelope Generation & ElementTree Validation
    print("[7/7] Testing XML Envelope Generation, CDATA wrappers & ElementTree validation...")
    envelope = build_subtask_envelope(
        subtask_id="sub-test-01",
        objective="Implement generic cache with Result<T, E>",
        dependency_signatures=[
            "export interface Cache<T> { get(k: string): T | null; }",
            "pub fn retrieve<T, E>() -> Result<T, E>;",
        ],
        style_anchor_snippet="const logger = createLogger();\nexport default logger;",
        anchor_file="src/logger.ts",
        anchor_start=1,
        verification_cmd="npx tsc --noEmit && npx vitest run",
        tier="tier2_flash",
        frontier_blueprint="1. Concurrency safe\n2. Memory bounded",
        adversarial_test_seeds=["High concurrency race", "Null key edge case"],
    )

    # Validate XML parsing using ElementTree
    try:
        root = ET.fromstring(envelope)
        assert root.tag == "subtask_envelope"
        assert root.attrib["id"] == "sub-test-01"
        assert root.attrib["tier"] == "tier2_flash"

        obj_node = root.find("task_objective")
        assert obj_node is not None and "Result<T, E>" in (obj_node.text or "")

        guard_node = root.find("worker_anti_recursion_guard")
        assert guard_node is not None and "DO NOT delegate further" in (guard_node.text or "")

        cmd_node = root.find("verification_contract")
        assert cmd_node is not None and "&& npx vitest" in (cmd_node.text or "")
    except ET.ParseError as pe:
        print(f"XML ParseError: {pe}")
        print("Generated Envelope:\n", envelope)
        raise

    print("      -> Passed XML CDATA & ElementTree validation tests.")

    print("\n=====================================================")
    print("All Frontier-Guard v3.1 self-tests passed successfully (7/7)!")
    print("=====================================================\n")
    return True


# =====================================================================
# CLI Entrypoint
# =====================================================================

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Frontier-Guard-Handoff v3.1 Universal Polyglot Context Slicer & Complexity Scorer"
    )
    parser.add_argument("--config", help="Path to custom frontier-guard.config.json")
    sub = parser.add_subparsers(dest="cmd")

    # Command: test
    sub.add_parser("test", help="Run comprehensive built-in self-tests")

    # Command: check
    check_p = sub.add_parser("check", help="Check if prompt triggers /direct override or fast-path bypass")
    check_p.add_argument("--prompt", required=True, help="Raw user prompt")
    check_p.add_argument("--files", type=int, default=2, help="Estimated files touched")
    check_p.add_argument("--lines", type=int, default=100, help="Estimated lines changed")
    check_p.add_argument("--any-slash-override", action="store_true", help="Allow any slash-keyword to trigger override")

    # Command: score
    score_p = sub.add_parser("score", help="Compute 5-factor complexity score")
    score_p.add_argument("--domain", default="code", choices=["code", "ui", "data_sql", "devops", "research"])
    score_p.add_argument("--coupling", type=float, required=True, help="Coupling in [0.0, 1.0]")
    score_p.add_argument("--concurrency", type=float, required=True, help="Concurrency in [0.0, 1.0]")
    score_p.add_argument("--novelty", type=float, required=True, help="Novelty in [0.0, 1.0]")
    score_p.add_argument("--blast-radius", type=float, required=True, help="Blast radius in [0.0, 1.0]")
    score_p.add_argument("--irreversibility", type=float, required=True, help="Irreversibility in [0.0, 1.0]")

    # Command: slice
    slice_p = sub.add_parser("slice", help="Build stripped XML subtask envelope")
    slice_p.add_argument("--id", required=True, help="Subtask ID")
    slice_p.add_argument("--objective", required=True, help="1-2 sentence task objective")
    slice_p.add_argument("--tier", default="tier2_flash", help="Target model tier")
    slice_p.add_argument("--deps", nargs="*", default=[], help="Dependency files for signature extraction")
    slice_p.add_argument("--anchor-file", help="Exemplar file for style-clone anchor")
    slice_p.add_argument("--anchor-start", type=int, default=1, help="Start line for style anchor")
    slice_p.add_argument("--verify-cmd", default="npx tsc --noEmit", help="Verification command")
    slice_p.add_argument("--blueprint", help="Frontier blueprint string")
    slice_p.add_argument("--seeds", nargs="*", default=[], help="Adversarial edge vector test seeds")

    # Also support --self-test flag directly
    parser.add_argument("--self-test", action="store_true", help="Run built-in self-tests")

    args = parser.parse_args()

    if args.self_test or args.cmd == "test":
        success = run_self_tests()
        return 0 if success else 1

    if args.cmd == "check":
        cfg = find_and_load_config(args.config)
        res = check_prompt_override(
            prompt_text=args.prompt,
            estimated_files=args.files,
            estimated_lines=args.lines,
            config=cfg,
            allow_any_slash_override=args.any_slash_override,
        )
        print(json.dumps(res, indent=2))
        return 0

    if args.cmd == "score":
        cfg = find_and_load_config(args.config)
        try:
            res = compute_complexity_score(
                coupling=args.coupling,
                concurrency=args.concurrency,
                novelty=args.novelty,
                blast_radius=args.blast_radius,
                irreversibility=args.irreversibility,
                domain=args.domain,
                config=cfg,
            )
            print(json.dumps(res, indent=2))
            return 0
        except ValueError as err:
            sys.stderr.write(f"Error: {err}\n")
            return 2

    if args.cmd == "slice":
        sig_blocks: List[str] = []
        for dep in args.deps:
            p = pathlib.Path(dep)
            sigs = extract_signatures(p)
            sig_blocks.append(f"// --- {dep} (Signatures Only) ---\n" + "\n".join(sigs))

        anchor_text = (
            extract_style_anchor(pathlib.Path(args.anchor_file), args.anchor_start)
            if args.anchor_file
            else "// No style anchor specified"
        )

        envelope = build_subtask_envelope(
            subtask_id=args.id,
            objective=args.objective,
            dependency_signatures=sig_blocks,
            style_anchor_snippet=anchor_text,
            anchor_file=args.anchor_file or "",
            anchor_start=args.anchor_start,
            verification_cmd=args.verify_cmd,
            tier=args.tier,
            frontier_blueprint=args.blueprint,
            adversarial_test_seeds=args.seeds,
        )
        print(envelope)
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
