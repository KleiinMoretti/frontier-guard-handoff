#!/usr/bin/env python3
"""
Frontier-Guard-Handoff v3.0 — Universal Polyglot Context Slicer & Complexity Scorer.

Supports:
- Instant Kill-Switch detection (`/direct`, `/max`, `/frontier`, `/bypass`)
- Fast-Path Inline Bypass detection (`<= 35 lines` and `<= 1 file`)
- 5-Factor Complexity Scoring across 5 domains (code, ui, data_sql, devops, research)
- Polyglot Signature Extraction (TS/JS, Python, Rust, Go, C/C++, Java, C#, Kotlin,
  Swift, SQL, Terraform/HCL, GraphQL/Protobuf) + 15-line Style-Clone Anchor injection.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
from typing import Dict, List

OVERRIDE_KEYWORDS = ("/direct", "/max", "/frontier", "/bypass")

SIGNATURE_PATTERNS = [
    # TypeScript / JavaScript
    re.compile(r"^\s*export\s+(?:default\s+)?(?:async\s+)?(?:function|interface|type|class|const|enum)\s+[A-Za-z0-9_]+.*$"),
    # Python
    re.compile(r"^\s*(?:async\s+)?def\s+[A-Za-z0-9_]+\s*\(.*$"),
    re.compile(r"^\s*class\s+[A-Za-z0-9_]+.*:$"),
    # Rust / Go
    re.compile(r"^\s*(?:pub\s+(?:async\s+)?fn|pub\s+struct|pub\s+enum|pub\s+trait|func\s+[A-Za-z0-9_]+)\s+.*$"),
    # Java / C# / Kotlin / Swift / C++
    re.compile(
        r"^\s*(?:public|protected|internal|open|export)\s+"
        r"(?:static\s+|final\s+|abstract\s+|virtual\s+|override\s+|async\s+)*"
        r"(?:class|interface|struct|enum|record|fun|func|[A-Za-z0-9_<>\[\],\s]+\s+[A-Za-z0-9_]+\s*\().*$"
    ),
    # SQL / BigQuery / dbt
    re.compile(r"^\s*CREATE\s+(?:OR\s+REPLACE\s+)?(?:TABLE|VIEW|MATERIALIZED\s+VIEW|FUNCTION|PROCEDURE)\s+.*$", re.IGNORECASE),
    # Terraform / HCL
    re.compile(r'^\s*(?:resource|module|variable|output|data)\s+"[^"]+".*$'),
]


def check_prompt_override(prompt_text: str, estimated_files: int = 2, estimated_lines: int = 100) -> Dict[str, object]:
    """Check if the prompt triggers the /direct kill-switch or Fast-Path Inline Bypass."""
    tokens = set(re.findall(r"/[a-zA-Z0-9_-]+", prompt_text.lower()))
    matched_kw = [kw for kw in OVERRIDE_KEYWORDS if kw in tokens]
    if matched_kw:
        return {
            "delegation_enabled": False,
            "reason": f"Kill-switch keyword detected: {matched_kw[0]}",
            "execution_mode": "INLINE_FRONTIER_DIRECT",
        }
    if estimated_files <= 1 and estimated_lines <= 35:
        return {
            "delegation_enabled": False,
            "reason": f"Fast-Path Inline Bypass ({estimated_files} file, ~{estimated_lines} lines <= 35)",
            "execution_mode": "INLINE_FAST_PATH",
        }
    return {
        "delegation_enabled": True,
        "reason": "Standard Quota-Preserving Adaptive Delegation active",
        "execution_mode": "ADAPTIVE_DELEGATION",
    }


def compute_complexity_score(
    coupling: float,
    concurrency: float,
    novelty: float,
    blast_radius: float,
    irreversibility: float,
    domain: str = "code",
) -> Dict[str, object]:
    """Compute the deterministic 5-factor complexity score C in [0.00, 1.00]."""
    score = round(
        0.25 * coupling
        + 0.25 * concurrency
        + 0.20 * novelty
        + 0.15 * blast_radius
        + 0.15 * irreversibility,
        3,
    )
    if score < 0.25:
        tier = "tier1_flash_lite"
        mode = "DIRECT_ASYNC_WORKER"
    elif score < 0.55:
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
        "requires_micro_audit": blast_radius >= 0.8 or irreversibility >= 0.8,
        "breakdown": {
            "coupling": coupling,
            "concurrency": concurrency,
            "novelty": novelty,
            "blast_radius": blast_radius,
            "irreversibility": irreversibility,
        },
    }


def extract_signatures(file_path: pathlib.Path, max_lines: int = 60) -> List[str]:
    """Extract only exported/public interface, table, resource, and function headers."""
    if not file_path.exists():
        return [f"// File not found: {file_path}"]
    lines = file_path.read_text(encoding="utf-8", errors="replace").splitlines()
    extracted: List[str] = []
    for idx, line in enumerate(lines, start=1):
        if any(pat.match(line) for pat in SIGNATURE_PATTERNS):
            cleaned = line.rstrip()
            if cleaned.endswith("{"):
                cleaned = cleaned[:-1].rstrip() + ";"
            extracted.append(f"L{idx}: {cleaned}")
            if len(extracted) >= max_lines:
                break
    return extracted


def extract_style_anchor(file_path: pathlib.Path, start_line: int = 1, num_lines: int = 15) -> str:
    """Extract a compact 15-line canonical style anchor from an exemplar file."""
    if not file_path.exists():
        return f"// Style anchor file not found: {file_path}"
    lines = file_path.read_text(encoding="utf-8", errors="replace").splitlines()
    lo = max(0, start_line - 1)
    hi = min(len(lines), lo + num_lines)
    return "\n".join(lines[lo:hi])


def main() -> int:
    parser = argparse.ArgumentParser(description="Frontier-Guard v3.0 Universal Context Slicer & Scorer")
    sub = parser.add_subparsers(dest="cmd", required=True)

    check_p = sub.add_parser("check", help="Check if prompt triggers /direct override or fast-path bypass")
    check_p.add_argument("--prompt", required=True, help="Raw user prompt")
    check_p.add_argument("--files", type=int, default=2, help="Estimated files touched")
    check_p.add_argument("--lines", type=int, default=100, help="Estimated lines changed")

    score_p = sub.add_parser("score", help="Compute 5-factor complexity score")
    score_p.add_argument("--domain", default="code", choices=["code", "ui", "data_sql", "devops", "research"])
    score_p.add_argument("--coupling", type=float, required=True)
    score_p.add_argument("--concurrency", type=float, required=True)
    score_p.add_argument("--novelty", type=float, required=True)
    score_p.add_argument("--blast-radius", type=float, required=True)
    score_p.add_argument("--irreversibility", type=float, required=True)

    slice_p = sub.add_parser("slice", help="Build stripped XML subtask envelope")
    slice_p.add_argument("--id", required=True, help="Subtask ID")
    slice_p.add_argument("--objective", required=True, help="1-2 sentence task objective")
    slice_p.add_argument("--deps", nargs="*", default=[], help="Dependency files for signature extraction")
    slice_p.add_argument("--anchor-file", help="Exemplar file for style-clone anchor")
    slice_p.add_argument("--anchor-start", type=int, default=1, help="Start line for style anchor")
    slice_p.add_argument("--verify-cmd", default="npx tsc --noEmit", help="Verification command")

    args = parser.parse_args()
    if args.cmd == "check":
        print(json.dumps(check_prompt_override(args.prompt, args.files, args.lines), indent=2))
        return 0

    if args.cmd == "score":
        res = compute_complexity_score(
            args.coupling,
            args.concurrency,
            args.novelty,
            args.blast_radius,
            args.irreversibility,
            args.domain,
        )
        print(json.dumps(res, indent=2))
        return 0

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
        envelope = (
            f'<subtask_envelope id="{args.id}">\n'
            f"  <task_objective>{args.objective}</task_objective>\n"
            f"  <dependency_signatures>\n{chr(10).join(sig_blocks)}\n  </dependency_signatures>\n"
            f'  <style_clone_anchor file="{args.anchor_file or ""}" start_line="{args.anchor_start}">\n'
            f"{anchor_text}\n"
            f"  </style_clone_anchor>\n"
            f"  <verification_contract>{args.verify_cmd}</verification_contract>\n"
            f"</subtask_envelope>"
        )
        print(envelope)
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
