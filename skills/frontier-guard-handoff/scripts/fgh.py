#!/usr/bin/env python3
"""fgh.py - Frontier Guard v5 command-line helper (Python 3.9+, stdlib only).

Subcommands
  switch   PROMPT                      detect /bypass-style and /lean switches
  route    --kind K --lines N ...      deterministic lane recommendation (JSON)
  brief    --goal ... --verify ...     build a worker brief (Markdown)
  sig      FILE...                     print signatures only (polyglot)
  scrub    [FILE|-]                    redact secrets from text
  ext      health | run ...            external text lane (Ollama/LM Studio/OmniRoute/FreeLLMAPI)
  ledger   record ... | stats          outcome ledger + gateway demotion
  install  --target global|workspace   install skill + compact always-on rule
  selftest                             run the bundled unit tests

Exit codes: 0 ok, 2 usage error, 3 refused by policy, 4 no gateway available
(fall back to an Antigravity Flash worker), 5 gateway/protocol error.
"""
from __future__ import annotations

import argparse
import ast
import copy
import json
import os
import pathlib
import re
import shutil
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

VERSION = "5.0.0"
SKILL_DIR = pathlib.Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = SKILL_DIR / "config.default.json"
RULE_ASSET = SKILL_DIR / "assets" / "GEMINI.rule.md"
SKILL_NAME = "frontier-guard-handoff"
RULE_BEGIN = "<!-- fgh:begin -->"
RULE_END = "<!-- fgh:end -->"

EXIT_OK, EXIT_USAGE, EXIT_REFUSED, EXIT_NO_GATEWAY, EXIT_GATEWAY_ERROR = 0, 2, 3, 4, 5


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #
_FALLBACK_CONFIG: Dict[str, Any] = {
    "version": VERSION,
    "switches": {
        "bypass": ["/bypass", "/direct", "/max", "/frontier", "/off", "/no-delegate"],
        "lean": ["/lean"],
    },
    "routing": {
        "inline_max_lines": 40,
        "inline_max_files": 2,
        "delegate_min_lines": 60,
        "explore_min_files": 3,
        "unverifiable_inline_max_lines": 120,
        "lean": {
            "inline_max_lines": 15,
            "inline_max_files": 1,
            "delegate_min_lines": 30,
            "unverifiable_inline_max_lines": 60,
        },
    },
    "high_risk_keywords": ["auth", "password", "payment", "migration", "concurrency", "security", "secret", "prod"],
    "external": {
        "enabled": True,
        "privacy": "scrub",
        "allow_remote": True,
        "timeout_s": 90,
        "retries": 1,
        "max_tokens": 4096,
        "temperature": 0.2,
        "gateways": [],
    },
    "ledger": {"path": ".agents/fgh-ledger.jsonl", "window": 10, "min_runs": 5, "min_pass_rate": 0.7},
}


def deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively merge ``override`` into a copy of ``base`` (lists are replaced)."""
    out = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def find_workspace_root(start: Optional[pathlib.Path] = None) -> pathlib.Path:
    """Walk up from ``start`` to the first directory containing ``.agents`` or ``.git``."""
    cur = (start or pathlib.Path.cwd()).resolve()
    for candidate in (cur, *cur.parents):
        if (candidate / ".agents").is_dir() or (candidate / ".git").exists():
            return candidate
    return cur


def load_config(start: Optional[pathlib.Path] = None) -> Dict[str, Any]:
    """Defaults <- skill config.default.json <- workspace .agents/fgh.config.json <- $FGH_CONFIG."""
    cfg = copy.deepcopy(_FALLBACK_CONFIG)
    layers: List[pathlib.Path] = [DEFAULT_CONFIG_PATH, find_workspace_root(start) / ".agents" / "fgh.config.json"]
    env_path = os.environ.get("FGH_CONFIG")
    if env_path:
        layers.append(pathlib.Path(env_path))
    for path in layers:
        if path.is_file():
            try:
                cfg = deep_merge(cfg, json.loads(path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError) as exc:
                print(f"fgh: ignoring unreadable config {path}: {exc}", file=sys.stderr)
    return cfg


# --------------------------------------------------------------------------- #
# Switch detection
# --------------------------------------------------------------------------- #
_SWITCH_RE = re.compile(r"(?:^|(?<=\s))(/[a-z][a-z0-9_-]*)(?=$|\s|[.,!?;:)\]])", re.IGNORECASE)


def detect_switch(prompt: str, cfg: Dict[str, Any]) -> Dict[str, Optional[str]]:
    """Return {"mode": "bypass"|"lean"|"normal", "keyword": ...}. Bypass wins over lean."""
    found = [m.group(1).lower() for m in _SWITCH_RE.finditer(prompt or "")]
    bypass = {k.lower() for k in cfg["switches"].get("bypass", [])}
    lean = {k.lower() for k in cfg["switches"].get("lean", [])}
    for kw in found:
        if kw in bypass:
            return {"mode": "bypass", "keyword": kw}
    for kw in found:
        if kw in lean:
            return {"mode": "lean", "keyword": kw}
    return {"mode": "normal", "keyword": None}


# --------------------------------------------------------------------------- #
# Routing
# --------------------------------------------------------------------------- #
KINDS = ("explore", "mechanical", "generate", "edit", "design", "debug", "review", "docs")

_TOOL_HINTS = {
    "rename": "IDE rename / `git grep -l OLD | xargs sed -i 's/OLD/NEW/g'` / language codemod (jscodeshift, ruff, gofmt -r)",
    "format": "prettier --write / ruff format / gofmt / cargo fmt / dotnet format",
    "lint": "eslint --fix / ruff check --fix / clippy --fix",
    "codegen": "openapi-generator / protoc / prisma generate / sqlc / graphql-codegen",
    "move": "git mv + one search/replace script for imports",
}


def is_high_risk(text: str, cfg: Dict[str, Any]) -> Optional[str]:
    """Return the first high-risk keyword found as a whole word/phrase in ``text``."""
    low = (text or "").lower()
    for kw in cfg.get("high_risk_keywords", []):
        if re.search(r"(?<![a-z0-9])" + re.escape(kw.lower()) + r"(?![a-z0-9])", low):
            return kw
    return None


def route(
    kind: str,
    lines: int,
    files: int,
    cfg: Dict[str, Any],
    spec: str = "full",
    verify: Optional[str] = None,
    risk: str = "auto",
    text_only: bool = False,
    task: str = "",
    prompt: str = "",
    tool_hint: Optional[str] = None,
) -> Dict[str, Any]:
    """Apply the SKILL.md section 2 decision procedure. Returns lane, reason and next step."""
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}")
    if lines < 0 or files < 0:
        raise ValueError("lines and files must be >= 0")

    sw = detect_switch(prompt, cfg)
    th = dict(cfg["routing"])
    if sw["mode"] == "lean":
        th.update(cfg["routing"].get("lean", {}))

    def out(lane: str, reason: str, nxt: str, **extra: Any) -> Dict[str, Any]:
        res = {"lane": lane, "reason": reason, "next": nxt, "mode": sw["mode"]}
        res.update(extra)
        return res

    if sw["mode"] == "bypass":
        return out("L1-inline", f"switch {sw['keyword']} active", "Do the whole turn inline.")

    if kind == "mechanical":
        hint = _TOOL_HINTS.get(tool_hint or "", "a formatter, linter --fix, codemod, generator, or a short script")
        return out("L0-tools", "deterministic transformation", f"Use {hint}; verify with the build/tests.")

    if kind == "explore":
        if files == 0 or files > th["explore_min_files"]:
            return out(
                "L2-scout",
                "exploration over many/unknown files",
                'invoke_subagent(TypeName:"fgh-scout", Model:"flash", Prompt:"[FGH-SCOUT] <question>; return <=300 words with file:line refs")',
            )
        return out("L1-inline", "exploration of a few known files", "grep, then read line ranges.")

    if kind in ("design", "debug", "review"):
        return out("L1-inline", f"{kind} needs frontier judgment", "Do it inline; delegate only follow-up specified work.")

    risk_kw = None
    if risk == "high":
        risk_kw = "flagged"
    elif risk == "auto":
        risk_kw = is_high_risk(task, cfg)
    if risk_kw:
        alt = None
        if lines >= th["delegate_min_lines"] and spec == "full" and verify:
            alt = "Large mechanical part may go to fgh-worker, followed by a FULL review of the diff. Never external."
        return out("L1-inline", f"high risk ({risk_kw})", "Implement inline.", alternative=alt)

    if lines <= th["inline_max_lines"] and files <= th["inline_max_files"]:
        return out("L1-inline", "small change; worker re-read overhead exceeds savings", "Edit inline.")

    if spec != "full":
        return out(
            "L1-inline",
            "design not settled",
            "Make the design decisions inline, write them into a brief (fgh.py brief), then re-route the remainder.",
        )

    if not verify:
        if lines <= th["unverifiable_inline_max_lines"]:
            return out("L1-inline", "no mechanical verification and moderate size", "Do it inline.")
        return out(
            "L2-worker+review",
            "large but not mechanically verifiable",
            'invoke_subagent(TypeName:"fgh-worker", Model:"flash", Prompt:<brief>) then review the result yourself.',
        )

    if lines < th["delegate_min_lines"]:
        return out("L1-inline", "grey zone; quality favoured over savings", "Do it inline.")

    worker = 'invoke_subagent(TypeName:"fgh-worker", Model:"flash", Role:"<role>", Prompt:<brief>)'
    if text_only and cfg.get("external", {}).get("enabled"):
        return out(
            "L3-external->L2-worker",
            "specified, verifiable, stateless text",
            f"python fgh.py ext run --brief <brief.md> --out <file>; on exit 3/4/5 or failed verify: {worker}",
        )
    return out("L2-worker", "specified, verifiable, large enough to pay off", worker)


# --------------------------------------------------------------------------- #
# Signature extraction
# --------------------------------------------------------------------------- #
_STR_RE = re.compile(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|`(?:\\.|[^`\\])*`')


def _clean(line: str) -> str:
    """Strip string literals and // or # comments so bracket counting is not fooled."""
    no_str = _STR_RE.sub('""', line)
    idx = no_str.find("//")
    if idx >= 0:
        no_str = no_str[:idx]
    return no_str


def _py_signatures(src: str) -> List[str]:
    tree = ast.parse(src)
    out: List[str] = []

    def doc_hint(node: ast.AST) -> str:
        doc = ast.get_docstring(node)  # type: ignore[arg-type]
        return f"  # {doc.strip().splitlines()[0][:100]}" if doc and doc.strip() else ""

    def visit(body: Sequence[ast.stmt], indent: str) -> None:
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name.startswith("_") and not (node.name.startswith("__") and node.name.endswith("__")):
                    continue
                for deco in node.decorator_list:
                    out.append(f"{indent}@{ast.unparse(deco)}")
                kw = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
                ret = f" -> {ast.unparse(node.returns)}" if node.returns is not None else ""
                out.append(f"{indent}{kw} {node.name}({ast.unparse(node.args)}){ret}: ...  # L{node.lineno}{doc_hint(node)}")
            elif isinstance(node, ast.ClassDef):
                if node.name.startswith("_"):
                    continue
                for deco in node.decorator_list:
                    out.append(f"{indent}@{ast.unparse(deco)}")
                bases = [ast.unparse(b) for b in node.bases] + [ast.unparse(k) for k in node.keywords]
                base_txt = f"({', '.join(bases)})" if bases else ""
                out.append(f"{indent}class {node.name}{base_txt}:  # L{node.lineno}{doc_hint(node)}")
                visit(node.body, indent + "    ")
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                if node.target.id.startswith("_"):
                    continue
                out.append(f"{indent}{node.target.id}: {ast.unparse(node.annotation)}")

    visit(tree.body, "")
    return out


_PY_FALLBACK_RE = re.compile(r"^\s*(?:async\s+)?def\s+\w+|^\s*class\s+\w+")


def _py_fallback(lines: List[str]) -> List[str]:
    out: List[str] = []
    i = 0
    while i < len(lines):
        if _PY_FALLBACK_RE.match(lines[i]):
            buf, depth, j = [], 0, i
            while j < len(lines) and len(buf) < 12:
                c = _clean(lines[j])
                buf.append(lines[j].rstrip())
                depth += c.count("(") - c.count(")")
                if depth <= 0 and c.rstrip().endswith(":"):
                    break
                j += 1
            out.append("\n".join(buf) + f"  # L{i + 1}")
            i = j + 1
        else:
            i += 1
    return out


class _Lang:
    def __init__(
        self,
        start: str,
        block: Optional[str] = None,
        container: Optional[str] = None,
        member: Optional[str] = None,
        flags: int = 0,
    ) -> None:
        self.start = re.compile(start, flags)
        self.block = re.compile(block, flags) if block else None
        self.container = re.compile(container, flags) if container else None
        self.member = re.compile(member, flags) if member else None


_MEMBER_SKIP = re.compile(r"^\s*(?:if|for|while|switch|return|catch|else|do|try|new|throw|await|yield)\b")

_TS_EXPORT = _Lang(
    start=r"^\s*export\s",
    block=r"^\s*export\s+(?:declare\s+)?(?:const\s+)?(?:interface|enum)\b|^\s*export\s+type\s+\w+[^=]*=\s*\{",
    container=r"^\s*export\s+(?:default\s+)?(?:abstract\s+)?class\b",
    member=r"^\s+(?:(?:public|protected|static|async|readonly|abstract|override|get|set)\s+)*[A-Za-z_$][\w$]*\??\s*(?:<[^>]*>)?\s*\(",
)
_TS_ALL = _Lang(
    start=r"^\s*(?:export\s+)?(?:default\s+)?(?:declare\s+)?(?:abstract\s+)?(?:async\s+)?(?:function|class|interface|enum|type)\b",
    block=r"^\s*(?:export\s+)?(?:declare\s+)?(?:interface|enum)\b|^\s*(?:export\s+)?type\s+\w+[^=]*=\s*\{",
    container=r"^\s*(?:export\s+)?(?:default\s+)?(?:abstract\s+)?class\b",
    member=_TS_EXPORT.member.pattern if _TS_EXPORT.member else None,
)
_LANGS: Dict[str, _Lang] = {
    "go": _Lang(start=r"^(?:func|type)\s", block=r"^type\s+\w+\s+(?:struct|interface)\s*\{"),
    "rust": _Lang(
        start=r"^\s*pub(?:\([a-z]+\))?\s+(?:async\s+)?(?:unsafe\s+)?(?:fn|struct|enum|trait|type|const|mod)\b|^\s*impl\b",
        block=r"^\s*pub(?:\([a-z]+\))?\s+(?:struct|enum)\b",
        container=r"^\s*(?:pub(?:\([a-z]+\))?\s+)?(?:impl|trait)\b",
        member=r"^\s+(?:pub(?:\([a-z]+\))?\s+)?(?:async\s+)?(?:unsafe\s+)?fn\b",
    ),
    "jvm": _Lang(
        start=r"^\s*(?:@\w+\s+)*(?:(?:public|protected|internal|open|abstract|final|sealed|static|data|partial)\s+)*(?:class|interface|enum|record|struct|object)\b"
        r"|^\s*(?:public|protected|internal)\s",
        block=r"^\s*(?:(?:public|protected|internal|static)\s+)*enum\b",
        container=r"^\s*(?:@\w+\s+)*(?:(?:public|protected|internal|open|abstract|final|sealed|static|data|partial)\s+)*(?:class|interface|record|struct|object)\b",
        member=r"^\s+(?:@\w+\s+)*(?:public|protected|internal|open|override)\b[^=;{]*\(",
    ),
}
_EXT_LANG = {
    ".go": "go",
    ".rs": "rust",
    ".java": "jvm",
    ".kt": "jvm",
    ".kts": "jvm",
    ".cs": "jvm",
    ".scala": "jvm",
    ".swift": "jvm",
}
_TS_EXTS = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts"}


def _brace_end(lines: List[str], start: int, cap: int = 400) -> int:
    """Return index of the line where braces opened at/after ``start`` balance back to zero."""
    depth, opened = 0, False
    for j in range(start, min(len(lines), start + cap)):
        c = _clean(lines[j])
        depth += c.count("{") - c.count("}")
        if "{" in c:
            opened = True
        if opened and depth <= 0:
            return j
    return start


_CONTINUATION = (",", "(", "<", "=", "|", "&", ":", "->", "extends", "implements")


def _header(lines: List[str], i: int, max_lines: int = 12) -> Tuple[List[str], int]:
    """Collect a declaration header until parens balance and a body/terminator token appears.

    Returns (header_lines_with_body_elided, index_of_last_header_line).
    """
    buf: List[str] = []
    depth = 0
    j = i
    while j < len(lines) and len(buf) < max_lines:
        c = _clean(lines[j])
        buf.append(lines[j].rstrip())
        depth += c.count("(") - c.count(")")
        s = c.rstrip()
        if depth <= 0 and ("{" in c or s.endswith(";") or "=>" in c):
            break
        if depth <= 0 and s and not s.endswith(_CONTINUATION):
            break  # one-line declaration, or body opens on the next line (Allman style)
        j += 1
    j = min(j, len(lines) - 1)
    last = buf[-1]
    brace = _clean(last).find("{")
    if brace >= 0:
        buf[-1] = last[: brace + 1] + " … }"
    return buf, j


def _body_open(lines: List[str], i: int, hend: int) -> Optional[int]:
    """Index of the line that opens the declaration body ('{'), allowing Allman style."""
    for k in range(i, hend + 1):
        if "{" in _clean(lines[k]):
            return k
    nxt = hend + 1
    while nxt < len(lines) and not lines[nxt].strip():
        nxt += 1
    if nxt < len(lines) and lines[nxt].strip().startswith("{"):
        return nxt
    return None


_REEXPORT = re.compile(r"^\s*export\s*(?:\*|\{|type\s*\{)")
_TRANSPARENT = re.compile(r"^\s*(?:export\s+)?(?:declare\s+)?(?:namespace|module)\b(?!\s*\.)")


def _c_like(lines: List[str], lang: _Lang) -> List[str]:
    out: List[str] = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        if _TRANSPARENT.match(line):
            open_at = _body_open(lines, i, i)
            i = (open_at + 1) if open_at is not None else (i + 1)
            continue
        if not lang.start.match(line):
            c = _clean(line)
            if c.count("{") > c.count("}"):
                i = _brace_end(lines, i) + 1  # skip non-public bodies entirely
            else:
                i += 1
            continue
        if _REEXPORT.match(line):
            out.append(line.rstrip() + f"  // L{i + 1}")
            i += 1
            continue
        if lang.block and lang.block.match(line):
            end = max(_brace_end(lines, i), i)
            block = [ln.rstrip() for ln in lines[i : min(end + 1, i + 30)]]
            if end + 1 > i + 30:
                block.append("  // … truncated")
            out.append("\n".join(block) + f"  // L{i + 1}")
            i = end + 1
            continue
        header, hend = _header(lines, i)
        out.append("\n".join(header) + f"  // L{i + 1}")
        open_at = _body_open(lines, i, hend)
        end = _brace_end(lines, open_at) if open_at is not None else hend
        if open_at is not None and lang.container and lang.container.match(line) and lang.member:
            k = open_at + 1
            while k < end:
                ml = lines[k]
                head = ml.split("(")[0]
                if lang.member.match(ml) and not _MEMBER_SKIP.match(ml) and "private" not in head and "#" not in head:
                    mh, mend = _header(lines, k)
                    out.append("\n".join("  " + h.strip() for h in mh))
                    mopen = _body_open(lines, k, mend)
                    k = (_brace_end(lines, mopen) if mopen is not None else mend) + 1
                else:
                    c = _clean(ml)
                    k = _brace_end(lines, k) + 1 if c.count("{") > c.count("}") else k + 1
        i = max(end, hend) + 1
    return out


_SQL_START = re.compile(
    r"^\s*CREATE\s+(?:OR\s+REPLACE\s+)?(?:TEMP(?:ORARY)?\s+)?(TABLE|VIEW|MATERIALIZED\s+VIEW|FUNCTION|PROCEDURE)\b", re.IGNORECASE
)
_SQL_STOP = re.compile(r"\bAS\b|\bBEGIN\b|\$\$", re.IGNORECASE)


def _sql(lines: List[str]) -> List[str]:
    out: List[str] = []
    i = 0
    while i < len(lines):
        m = _SQL_START.match(lines[i])
        if not m:
            i += 1
            continue
        is_table = m.group(1).upper() == "TABLE"
        cap = 40 if is_table else 8
        buf, j = [], i
        while j < len(lines) and len(buf) < cap:
            buf.append(lines[j].rstrip())
            if lines[j].rstrip().endswith(";") or (not is_table and _SQL_STOP.search(lines[j])):
                break
            j += 1
        out.append("\n".join(buf) + f"  -- L{i + 1}")
        i = j + 1
    return out


_HCL_START = re.compile(r'^(resource|module|variable|output|data|provider)\s+"')


def _hcl(lines: List[str]) -> List[str]:
    out: List[str] = []
    i = 0
    while i < len(lines):
        m = _HCL_START.match(lines[i])
        if not m:
            i += 1
            continue
        end = _brace_end(lines, i)
        if m.group(1) in ("variable", "output") and end - i < 15:
            out.append("\n".join(ln.rstrip() for ln in lines[i : end + 1]) + f"  # L{i + 1}")
        else:
            out.append(lines[i].rstrip().rstrip("{").rstrip() + " { … }" + f"  # L{i + 1}")
        i = max(end, i) + 1
    return out


def extract_signatures(path: pathlib.Path, max_lines: int = 150) -> str:
    """Return a signatures-only view of ``path`` (language picked by extension)."""
    try:
        src = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return f"// cannot read {path}: {exc}"
    lines = src.splitlines()
    ext = path.suffix.lower()
    if ext in (".py", ".pyi"):
        try:
            items = _py_signatures(src)
        except SyntaxError:
            items = _py_fallback(lines)
    elif ext in _TS_EXTS:
        lang = _TS_EXPORT if any(re.match(r"^\s*export\s", ln) for ln in lines) else _TS_ALL
        items = _c_like(lines, lang)
    elif ext in _EXT_LANG:
        items = _c_like(lines, _LANGS[_EXT_LANG[ext]])
    elif ext == ".sql":
        items = _sql(lines)
    elif ext in (".tf", ".hcl"):
        items = _hcl(lines)
    else:
        items = [ln.rstrip() for ln in lines if re.match(r"^\s*(?:export|public|pub|def|func|function|class|interface|struct|type)\b", ln)]
    text_lines = "\n".join(items).splitlines()
    if len(text_lines) > max_lines:
        text_lines = text_lines[:max_lines] + [f"… truncated ({len(text_lines) - max_lines} more lines)"]
    return "\n".join(text_lines)


# --------------------------------------------------------------------------- #
# Briefs
# --------------------------------------------------------------------------- #
_LANG_TAG = {".py": "python", ".ts": "ts", ".tsx": "tsx", ".js": "js", ".jsx": "jsx", ".go": "go", ".rs": "rust",
             ".java": "java", ".kt": "kotlin", ".cs": "csharp", ".sql": "sql", ".tf": "hcl", ".swift": "swift"}


def fence(content: str, lang: str = "") -> str:
    """Wrap ``content`` in a backtick fence longer than any backtick run inside it."""
    longest = max((len(m.group(0)) for m in re.finditer(r"`+", content)), default=0)
    ticks = "`" * max(3, longest + 1)
    return f"{ticks}{lang}\n{content.rstrip()}\n{ticks}"


def parse_anchor(spec: str) -> Tuple[pathlib.Path, int, int]:
    """Parse ``path[:start[-end]]`` (Windows drive letters are handled)."""
    m = re.match(r"^(.*?)(?::(\d+)(?:-(\d+))?)?$", spec)
    if not m:
        raise ValueError(f"bad anchor spec: {spec}")
    path = pathlib.Path(m.group(1))
    start = int(m.group(2)) if m.group(2) else 1
    end = int(m.group(3)) if m.group(3) else start + 14
    if end < start:
        raise ValueError("anchor end < start")
    return path, start, min(end, start + 19)


def build_brief(
    goal: str,
    own: Sequence[str],
    verify: str,
    contracts: Sequence[str] = (),
    anchor: Optional[str] = None,
    decisions: Sequence[str] = (),
    edges: Sequence[str] = (),
    context: Sequence[str] = (),
    role: str = "worker",
) -> str:
    if not goal.strip():
        raise ValueError("goal is required")
    if not own:
        raise ValueError("at least one --own file is required")
    if not verify.strip():
        raise ValueError("verify command is required (delegate only verifiable work)")
    parts: List[str] = [f"[FGH-{role.upper()}]", "", "## Goal", goal.strip(), "", "## Files you own",
                        "Create/modify ONLY these files. Touch nothing else; if you must, stop and report why."]
    parts += [f"- `{f}`" for f in own]
    if decisions:
        parts += ["", "## Decisions already made (do not revisit)"] + [f"- {d}" for d in decisions]
    if contracts:
        parts += ["", "## Contracts (signatures only)"]
        for c in contracts:
            p = pathlib.Path(c)
            parts += [f"### `{c}`", fence(extract_signatures(p), _LANG_TAG.get(p.suffix.lower(), ""))]
    if anchor:
        path, start, end = parse_anchor(anchor)
        try:
            src_lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            snippet = "\n".join(src_lines[start - 1 : end])
        except OSError as exc:
            snippet = f"(cannot read anchor: {exc})"
        parts += ["", f"## Style anchor — mirror this exactly (`{path}` L{start}-{end})",
                  fence(snippet, _LANG_TAG.get(path.suffix.lower(), ""))]
    if context:
        parts += ["", "## Extra context"] + [f"- {c}" for c in context]
    if edges:
        parts += ["", "## Edge cases you must handle and test"] + [f"- {e}" for e in edges]
    parts += ["", "## Verify", fence(verify.strip(), "bash"),
              "Run it. Iterate until it passes (max 3 attempts), then report.",
              "", "## Report (<=150 words)",
              "- STATUS: PASS | FAIL", "- FILES: changed paths", "- VERIFY: last 15 lines of output",
              "- NOTES: assumptions or open questions (only if any)"]
    return scrub(("\n".join(parts)).rstrip() + "\n")[0]


# --------------------------------------------------------------------------- #
# Secret scrubber
# --------------------------------------------------------------------------- #
_SCRUB_PATTERNS: List[Tuple[str, "re.Pattern[str]", int]] = [
    ("private-key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"), 0),
    ("aws-key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), 0),
    ("github-token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})\b"), 0),
    ("openai-anthropic-key", re.compile(r"\bsk-(?:proj-|ant-|live-|test-)?[A-Za-z0-9_-]{20,}"), 0),
    ("google-key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"), 0),
    ("slack-token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"), 0),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"), 0),
    ("url-credential", re.compile(r"(?<=://)[^\s:/@]+:([^\s@/]{3,})(?=@)"), 1),
    ("env-secret", re.compile(r"(?m)^\s*(?:export\s+)?[A-Z0-9_]*(?:PASSWORD|PASSWD|SECRET|API_KEY|APIKEY|TOKEN|ACCESS_KEY|PRIVATE_KEY)[A-Z0-9_]*\s*=\s*[\"']?([^\s\"'#]{6,})"), 1),
    ("quoted-secret", re.compile(r"(?i)(?:password|passwd|secret|api[_-]?key|access[_-]?key|auth[_-]?token|token)[\"']?\s*[:=]\s*([\"'])([^\"'\s]{8,})\1"), 2),
]


def scrub(text: str) -> Tuple[str, Dict[str, int]]:
    """Redact credentials. Returns (scrubbed_text, counts_by_kind)."""
    counts: Dict[str, int] = {}
    for kind, pattern, group in _SCRUB_PATTERNS:
        def repl(m: "re.Match[str]", kind: str = kind, group: int = group) -> str:
            counts[kind] = counts.get(kind, 0) + 1
            if group == 0:
                return f"[REDACTED:{kind}]"
            s, e = m.span(group)
            base = m.start(0)
            whole = m.group(0)
            return whole[: s - base] + f"[REDACTED:{kind}]" + whole[e - base :]
        text = pattern.sub(repl, text)
    return text, counts


# --------------------------------------------------------------------------- #
# Ledger
# --------------------------------------------------------------------------- #
def ledger_path(cfg: Dict[str, Any], start: Optional[pathlib.Path] = None) -> pathlib.Path:
    p = pathlib.Path(cfg["ledger"]["path"])
    return p if p.is_absolute() else find_workspace_root(start) / p


def ledger_record(path: pathlib.Path, lane: str, task: str, passed: bool, gateway: Optional[str] = None, note: str = "") -> Dict[str, Any]:
    entry = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "lane": lane, "task": task, "passed": bool(passed)}
    if gateway:
        entry["gateway"] = gateway
    if note:
        entry["note"] = note[:300]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")
    return entry


def ledger_read(path: pathlib.Path) -> List[Dict[str, Any]]:
    if not path.is_file():
        return []
    rows: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict) and "passed" in row:
            rows.append(row)
    return rows


def ledger_stats(rows: Iterable[Dict[str, Any]], cfg: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    lcfg = cfg["ledger"]
    groups: Dict[str, List[bool]] = {}
    for row in rows:
        key = row.get("gateway") or row.get("lane", "?")
        groups.setdefault(key, []).append(bool(row["passed"]))
    stats: Dict[str, Dict[str, Any]] = {}
    for key, results in groups.items():
        window = results[-int(lcfg["window"]):]
        rate = sum(window) / len(window)
        stats[key] = {
            "runs_total": len(results),
            "window_runs": len(window),
            "pass_rate": round(rate, 3),
            "demoted": len(window) >= int(lcfg["min_runs"]) and rate < float(lcfg["min_pass_rate"]),
        }
    return stats


# --------------------------------------------------------------------------- #
# External lane
# --------------------------------------------------------------------------- #
WORKER_SYSTEM_PROMPT = (
    "You are a code-generation worker. Follow the brief exactly; it is the whole specification. "
    "Mirror the style anchor. Do not add features, files, or commentary. "
    "Output each requested file as one fenced code block preceded by a line `FILE: <path>`."
)


def _http_json(url: str, payload: Optional[Dict[str, Any]], headers: Dict[str, str], timeout: float) -> Dict[str, Any]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json", **headers},
                                 method="POST" if payload is not None else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (configured local/self-hosted gateways)
        body = resp.read().decode("utf-8", errors="replace")
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ValueError(f"non-JSON response: {body[:120]!r}") from exc
    if not isinstance(parsed, dict):
        raise ValueError("unexpected JSON shape")
    return parsed


def _auth_headers(gw: Dict[str, Any]) -> Dict[str, str]:
    env = gw.get("api_key_env")
    key = os.environ.get(env) if env else None
    return {"Authorization": f"Bearer {key}"} if key else {}


def gateway_reachable(gw: Dict[str, Any], timeout: float = 3.0) -> bool:
    try:
        _http_json(gw["base_url"].rstrip("/") + "/models", None, _auth_headers(gw), timeout)
        return True
    except Exception:  # noqa: BLE001 - any failure means unreachable
        return False


def eligible_gateways(cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    ext = cfg["external"]
    gws = list(ext.get("gateways", []))
    if ext.get("privacy") == "local_only" or not ext.get("allow_remote", True):
        gws = [g for g in gws if g.get("local")]
    gws.sort(key=lambda g: 0 if g.get("local") else 1)
    return gws


def external_policy(brief: str, cfg: Dict[str, Any], stats: Dict[str, Dict[str, Any]], gateway: Optional[str], risk: str) -> Optional[str]:
    """Return a refusal reason, or None if the external lane may run."""
    if not cfg["external"].get("enabled", False):
        return "external lane disabled in config"
    if risk == "high":
        return "high-risk work never goes to the external lane"
    kw = is_high_risk(brief.split("## Contracts")[0], cfg) if risk == "auto" else None
    if kw:
        return f"brief looks high-risk ({kw}); use an Antigravity worker or inline"
    m = re.search(r"## Verify\s*\n+(`{3,})[^\n]*\n(.*?)\n\1", brief, re.DOTALL)
    if not m or not m.group(2).strip() or m.group(2).strip().lower() in ("none", "n/a"):
        return "brief has no verify command; external output must be mechanically verified"
    if gateway and stats.get(gateway, {}).get("demoted"):
        return f"gateway {gateway} is demoted by the ledger"
    return None


def select_gateway(cfg: Dict[str, Any], stats: Dict[str, Dict[str, Any]], explicit: Optional[str],
                   reachable: Callable[[Dict[str, Any]], bool] = gateway_reachable) -> Optional[Dict[str, Any]]:
    for gw in eligible_gateways(cfg):
        if explicit and gw["name"] != explicit:
            continue
        if stats.get(gw["name"], {}).get("demoted"):
            continue
        if reachable(gw):
            return gw
    return None


_CODE_BLOCK_RE = re.compile(r"^(`{3,})[^\n]*\n(.*?)^\1[ \t]*$", re.DOTALL | re.MULTILINE)


def extract_code(content: str) -> str:
    blocks = [m.group(2) for m in _CODE_BLOCK_RE.finditer(content)]
    return "\n".join(b.rstrip("\n") for b in blocks) + "\n" if blocks else content


def external_run(brief: str, cfg: Dict[str, Any], gw: Dict[str, Any], model: Optional[str] = None) -> Dict[str, Any]:
    ext = cfg["external"]
    payload_text, redactions = scrub(brief) if ext.get("privacy", "scrub") != "off" else (brief, {})
    payload = {
        "model": model or gw.get("model") or "auto",
        "messages": [{"role": "system", "content": WORKER_SYSTEM_PROMPT}, {"role": "user", "content": payload_text}],
        "max_tokens": int(ext.get("max_tokens", 4096)),
        "temperature": float(ext.get("temperature", 0.2)),
    }
    url = gw["base_url"].rstrip("/") + "/chat/completions"
    attempts = int(ext.get("retries", 1)) + 1
    last_err = "unknown error"
    t0 = time.time()
    for attempt in range(attempts):
        try:
            resp = _http_json(url, payload, _auth_headers(gw), float(ext.get("timeout_s", 90)))
            choices = resp.get("choices") or []
            content = (choices[0].get("message") or {}).get("content") if choices else None
            if not content or not str(content).strip():
                raise ValueError("empty completion")
            return {"content": str(content), "redactions": redactions, "usage": resp.get("usage"),
                    "latency_ms": int((time.time() - t0) * 1000), "model": payload["model"]}
        except urllib.error.HTTPError as exc:
            last_err = f"HTTP {exc.code}"
            if exc.code not in (408, 429, 500, 502, 503, 504):
                break
        except (urllib.error.URLError, TimeoutError, ValueError, KeyError, IndexError, AttributeError) as exc:
            last_err = f"{type(exc).__name__}: {exc}"
        if attempt + 1 < attempts:
            time.sleep(min(2 ** attempt, 8))
    raise RuntimeError(last_err)


# --------------------------------------------------------------------------- #
# Install
# --------------------------------------------------------------------------- #
_LEGACY_HEADINGS = ("# Global Quota-Preserving Adaptive Delegator Rule", "# Workspace Quota-Preserving Adaptive Delegator Rule")


def upsert_rule(rule_file: pathlib.Path, rule_text: str, replace_legacy: bool = False, dry_run: bool = False) -> str:
    block = f"{RULE_BEGIN}\n{rule_text.strip()}\n{RULE_END}\n"
    existing = rule_file.read_text(encoding="utf-8") if rule_file.is_file() else ""
    if RULE_BEGIN in existing and RULE_END in existing:
        pre, rest = existing.split(RULE_BEGIN, 1)
        _, post = rest.split(RULE_END, 1)
        new, action = pre + block + post.lstrip("\n"), "updated"
    elif existing.lstrip().startswith(_LEGACY_HEADINGS):
        if not replace_legacy:
            return "legacy-found (re-run with --replace-legacy to back it up and replace it)"
        if not dry_run:
            rule_file.with_suffix(rule_file.suffix + ".bak").write_text(existing, encoding="utf-8")
        new, action = block, "replaced-legacy (backup: .bak)"
    else:
        new, action = (existing.rstrip() + "\n\n" if existing.strip() else "") + block, "appended"
    if not dry_run:
        rule_file.parent.mkdir(parents=True, exist_ok=True)
        rule_file.write_text(new, encoding="utf-8")
    return action


def install(target: str, workspace: Optional[pathlib.Path], replace_legacy: bool, dry_run: bool,
            home: Optional[pathlib.Path] = None) -> Dict[str, str]:
    if target == "global":
        base = (home or pathlib.Path.home()) / ".gemini" / "config"
        skill_dest, rule_file = base / "skills" / SKILL_NAME, base / "GEMINI.md"
    else:
        ws = (workspace or find_workspace_root()).resolve()
        skill_dest, rule_file = ws / ".agents" / "skills" / SKILL_NAME, ws / "GEMINI.md"
    result = {"skill": str(skill_dest), "rule_file": str(rule_file)}
    if skill_dest.resolve() != SKILL_DIR.resolve():
        if not dry_run:
            if skill_dest.exists():
                shutil.rmtree(skill_dest)
            shutil.copytree(SKILL_DIR, skill_dest, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        result["skill_action"] = "copied"
    else:
        result["skill_action"] = "already in place"
    rule_text = RULE_ASSET.read_text(encoding="utf-8") if RULE_ASSET.is_file() else ""
    result["rule_action"] = upsert_rule(rule_file, rule_text, replace_legacy, dry_run) if rule_text else "rule asset missing"
    return result


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _print(obj: Any) -> None:
    print(json.dumps(obj, indent=2, ensure_ascii=False))


def _read_text_arg(arg: str) -> str:
    return sys.stdin.read() if arg == "-" else pathlib.Path(arg).read_text(encoding="utf-8", errors="replace")


def _bool(v: str) -> bool:
    if v.lower() in ("true", "1", "yes", "pass", "passed"):
        return True
    if v.lower() in ("false", "0", "no", "fail", "failed"):
        return False
    raise argparse.ArgumentTypeError("expected true/false")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="fgh", description=f"Frontier Guard v{VERSION}")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("switch", help="detect /bypass-style and /lean switches")
    s.add_argument("prompt")

    r = sub.add_parser("route", help="recommend a lane")
    r.add_argument("--kind", required=True, choices=KINDS)
    r.add_argument("--lines", type=int, default=0, help="estimated changed/generated lines")
    r.add_argument("--files", type=int, default=0, help="files touched (explore: files to scan; 0 = unknown)")
    r.add_argument("--spec", choices=("full", "partial", "none"), default="full")
    r.add_argument("--verify", default=None, help="verification command, if any")
    r.add_argument("--risk", choices=("auto", "low", "high"), default="auto")
    r.add_argument("--text-only", action="store_true", help="output is stateless text (tests, docs, fixtures)")
    r.add_argument("--task", default="", help="short task description (used for risk detection)")
    r.add_argument("--prompt", default="", help="raw user prompt (switch detection)")
    r.add_argument("--tool-hint", choices=sorted(_TOOL_HINTS), default=None)

    b = sub.add_parser("brief", help="build a worker brief")
    b.add_argument("--goal", required=True)
    b.add_argument("--own", nargs="+", required=True)
    b.add_argument("--verify", required=True)
    b.add_argument("--contracts", nargs="*", default=[])
    b.add_argument("--anchor", default=None, help="path[:start[-end]] (max 20 lines)")
    b.add_argument("--decision", action="append", default=[])
    b.add_argument("--edge", action="append", default=[])
    b.add_argument("--context", action="append", default=[])
    b.add_argument("--role", choices=("worker", "scout"), default="worker")
    b.add_argument("--out", default=None)

    g = sub.add_parser("sig", help="signatures only")
    g.add_argument("files", nargs="+")
    g.add_argument("--max-lines", type=int, default=150)

    c = sub.add_parser("scrub", help="redact secrets")
    c.add_argument("file", nargs="?", default="-")

    e = sub.add_parser("ext", help="external text lane")
    esub = e.add_subparsers(dest="ext_cmd", required=True)
    esub.add_parser("health")
    er = esub.add_parser("run")
    er.add_argument("--brief", required=True, help="brief file or - for stdin")
    er.add_argument("--out", required=True)
    er.add_argument("--gateway", default=None)
    er.add_argument("--model", default=None)
    er.add_argument("--risk", choices=("auto", "low", "high"), default="auto")
    er.add_argument("--raw", action="store_true", help="write raw completion instead of extracted code")
    er.add_argument("--task", default=None, help="task id for automatic ledger entry on gateway errors")

    l = sub.add_parser("ledger", help="outcome ledger")
    lsub = l.add_subparsers(dest="ledger_cmd", required=True)
    lr = lsub.add_parser("record")
    lr.add_argument("--lane", required=True)
    lr.add_argument("--task", required=True)
    lr.add_argument("--passed", required=True, type=_bool)
    lr.add_argument("--gateway", default=None)
    lr.add_argument("--note", default="")
    lsub.add_parser("stats")

    i = sub.add_parser("install", help="install skill + compact rule")
    i.add_argument("--target", choices=("global", "workspace"), required=True)
    i.add_argument("--workspace", default=None)
    i.add_argument("--replace-legacy", action="store_true")
    i.add_argument("--dry-run", action="store_true")

    sub.add_parser("selftest", help="run bundled unit tests")
    sub.add_parser("version")
    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    cfg = load_config()
    try:
        if args.cmd == "version":
            print(VERSION)
        elif args.cmd == "switch":
            _print(detect_switch(args.prompt, cfg))
        elif args.cmd == "route":
            _print(route(args.kind, args.lines, args.files, cfg, args.spec, args.verify, args.risk,
                         args.text_only, args.task, args.prompt, args.tool_hint))
        elif args.cmd == "brief":
            text = build_brief(args.goal, args.own, args.verify, args.contracts, args.anchor,
                               args.decision, args.edge, args.context, args.role)
            if args.out:
                out = pathlib.Path(args.out)
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(text, encoding="utf-8")
                _print({"brief": str(out), "chars": len(text), "approx_tokens": len(text) // 4})
            else:
                sys.stdout.write(text)
        elif args.cmd == "sig":
            for f in args.files:
                print(f"## {f}")
                print(extract_signatures(pathlib.Path(f), args.max_lines))
        elif args.cmd == "scrub":
            text, counts = scrub(_read_text_arg(args.file))
            sys.stdout.write(text)
            print(json.dumps({"redactions": counts}), file=sys.stderr)
        elif args.cmd == "ext":
            lpath = ledger_path(cfg)
            stats = ledger_stats(ledger_read(lpath), cfg)
            if args.ext_cmd == "health":
                _print([{"name": g["name"], "local": bool(g.get("local")), "model": g.get("model"),
                         "eligible": g in eligible_gateways(cfg), "key_present": bool(g.get("api_key_env") and os.environ.get(g["api_key_env"])),
                         "reachable": gateway_reachable(g), "demoted": stats.get(g["name"], {}).get("demoted", False)}
                        for g in cfg["external"].get("gateways", [])])
                return EXIT_OK
            brief = _read_text_arg(args.brief)
            reason = external_policy(brief, cfg, stats, args.gateway, args.risk)
            if reason:
                _print({"status": "refused", "reason": reason, "fallback": "fgh-worker (flash)"})
                return EXIT_REFUSED
            gw = select_gateway(cfg, stats, args.gateway)
            if not gw:
                _print({"status": "no_gateway", "fallback": "fgh-worker (flash)"})
                return EXIT_NO_GATEWAY
            try:
                res = external_run(brief, cfg, gw, args.model)
            except RuntimeError as exc:
                if args.task:
                    ledger_record(lpath, "L3", args.task, False, gw["name"], f"gateway error: {exc}")
                _print({"status": "gateway_error", "gateway": gw["name"], "error": str(exc), "fallback": "fgh-worker (flash)"})
                return EXIT_GATEWAY_ERROR
            out = pathlib.Path(args.out)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(res["content"] if args.raw else extract_code(res["content"]), encoding="utf-8")
            _print({"status": "ok", "gateway": gw["name"], "model": res["model"], "out": str(out),
                    "redactions": res["redactions"], "latency_ms": res["latency_ms"], "usage": res["usage"],
                    "next": f"run the brief's verify command, then: fgh.py ledger record --lane L3 --gateway {gw['name']} --task <id> --passed true|false"})
        elif args.cmd == "ledger":
            lpath = ledger_path(cfg)
            if args.ledger_cmd == "record":
                _print(ledger_record(lpath, args.lane, args.task, args.passed, args.gateway, args.note))
            else:
                _print({"ledger": str(lpath), "stats": ledger_stats(ledger_read(lpath), cfg)})
        elif args.cmd == "install":
            ws = pathlib.Path(args.workspace) if args.workspace else None
            _print(install(args.target, ws, args.replace_legacy, args.dry_run))
        elif args.cmd == "selftest":
            import unittest

            suite = unittest.defaultTestLoader.discover(str(SKILL_DIR / "tests"), pattern="test_*.py", top_level_dir=str(SKILL_DIR / "tests"))
            result = unittest.TextTestRunner(verbosity=1).run(suite)
            return EXIT_OK if result.wasSuccessful() else 1
    except ValueError as exc:
        print(f"fgh: {exc}", file=sys.stderr)
        return EXIT_USAGE
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
