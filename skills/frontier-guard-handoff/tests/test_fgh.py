"""Unit tests for fgh.py. Run: python scripts/fgh.py selftest  (or python -m unittest discover tests)."""
from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import textwrap
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))
import fgh  # noqa: E402

CFG = fgh.load_config()


def write(tmp: pathlib.Path, name: str, content: str) -> pathlib.Path:
    p = tmp / name
    p.write_text(textwrap.dedent(content).lstrip("\n"), encoding="utf-8")
    return p


class SwitchTests(unittest.TestCase):
    def test_bypass_keywords(self):
        for prompt in ("/bypass do it", "please /direct now", "fix this /max.", "(/off)"[1:]):
            self.assertEqual(fgh.detect_switch(prompt, CFG)["mode"], "bypass", prompt)

    def test_paths_and_urls_do_not_trigger(self):
        for prompt in ("edit src/direct/index.ts", "see https://x.com/max/page", "C:/off/file.txt", "a/bypass"):
            self.assertEqual(fgh.detect_switch(prompt, CFG)["mode"], "normal", prompt)

    def test_lean_and_precedence(self):
        self.assertEqual(fgh.detect_switch("/lean refactor", CFG)["mode"], "lean")
        self.assertEqual(fgh.detect_switch("/lean /bypass", CFG)["mode"], "bypass")
        self.assertEqual(fgh.detect_switch("/BYPASS", CFG)["mode"], "bypass")


class RouteTests(unittest.TestCase):
    def r(self, **kw):
        base = dict(kind="generate", lines=200, files=3, cfg=CFG, spec="full", verify="pytest -q", task="write tests")
        base.update(kw)
        return fgh.route(**base)["lane"]

    def test_bypass(self):
        self.assertEqual(self.r(prompt="/direct go"), "L1-inline")

    def test_mechanical(self):
        self.assertEqual(self.r(kind="mechanical"), "L0-tools")

    def test_explore(self):
        self.assertEqual(self.r(kind="explore", files=0), "L2-scout")
        self.assertEqual(self.r(kind="explore", files=10), "L2-scout")
        self.assertEqual(self.r(kind="explore", files=2), "L1-inline")

    def test_design_debug_review_inline(self):
        for k in ("design", "debug", "review"):
            self.assertEqual(self.r(kind=k), "L1-inline")

    def test_small_inline(self):
        self.assertEqual(self.r(lines=30, files=1), "L1-inline")

    def test_unspecified_inline(self):
        self.assertEqual(self.r(spec="partial"), "L1-inline")

    def test_high_risk(self):
        self.assertEqual(self.r(task="rewrite the payment webhook handler"), "L1-inline")
        self.assertEqual(self.r(risk="high", task="x"), "L1-inline")
        self.assertEqual(self.r(task="build a product page"), "L2-worker")  # 'prod' must not match 'product'

    def test_unverifiable(self):
        self.assertEqual(self.r(verify=None, lines=100), "L1-inline")
        self.assertEqual(self.r(verify=None, lines=300), "L2-worker+review")

    def test_grey_zone(self):
        self.assertEqual(self.r(lines=50), "L1-inline")

    def test_worker_and_external(self):
        self.assertEqual(self.r(), "L2-worker")
        self.assertEqual(self.r(text_only=True), "L3-external->L2-worker")

    def test_lean_lowers_thresholds(self):
        self.assertEqual(self.r(lines=35, files=2), "L1-inline")
        self.assertEqual(self.r(lines=35, files=2, prompt="/lean"), "L2-worker")

    def test_bad_input(self):
        with self.assertRaises(ValueError):
            fgh.route("nope", 1, 1, CFG)
        with self.assertRaises(ValueError):
            fgh.route("generate", -1, 1, CFG)


class SignatureTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.tmp = pathlib.Path(self.tmpdir.name)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_python_multiline_and_classes(self):
        p = write(self.tmp, "m.py", '''
            from dataclasses import dataclass

            @dataclass
            class Order:
                """An order."""
                id: str
                total: float

                def apply(
                    self,
                    discount: float = 0.0,
                    *,
                    reason: str | None = None,
                ) -> "Order":
                    return self

                def _hidden(self): ...

            async def fetch(url: str, timeout: int = 5) -> bytes:
                """Fetch bytes."""
                return b""

            def _private(): ...
        ''')
        sig = fgh.extract_signatures(p)
        self.assertIn("@dataclass", sig)
        self.assertIn("class Order:", sig)
        self.assertIn("id: str", sig)
        self.assertIn("def apply(self, discount: float=0.0, *, reason: str | None=None) -> 'Order'", sig)
        self.assertIn("async def fetch(url: str, timeout: int=5) -> bytes", sig)
        self.assertIn("# Fetch bytes.", sig)
        self.assertNotIn("_hidden", sig)
        self.assertNotIn("_private", sig)
        self.assertNotIn("return", sig)

    def test_python_syntax_error_fallback(self):
        p = write(self.tmp, "broken.py", "def ok(a,\n       b):\n    pass\ndef broken(:\n")
        sig = fgh.extract_signatures(p)
        self.assertIn("def ok(a,", sig)
        self.assertIn("b):", sig)

    def test_typescript(self):
        p = write(self.tmp, "a.ts", '''
            import { x } from "./x";
            export interface User {
              id: string;
              name?: string;
            }
            export type Result<T, E> = { ok: true; value: T } | { ok: false; error: E };
            export enum Role { Admin, User }
            export async function getUser(
              id: string,
              opts: { cache?: boolean } = {},
            ): Promise<Result<User, Error>> {
              const s = "{ not a brace";
              return { ok: true, value: { id } };
            }
            function helper() { return 1; }
            export class Repo extends Base {
              private secret = 1;
              constructor(private db: Db) { super(); }
              async find(id: string): Promise<User | null> {
                if (id) { return null; }
                return null;
              }
              #internal() {}
            }
            export { helper as h } from "./h";
            export const LIMIT = 10;
        ''')
        sig = fgh.extract_signatures(p)
        self.assertIn("name?: string;", sig)  # full interface body kept
        self.assertIn("export type Result<T, E>", sig)
        self.assertIn("export enum Role", sig)
        self.assertIn("opts: { cache?: boolean } = {},", sig)
        self.assertIn("): Promise<Result<User, Error>> { … }", sig)
        self.assertNotIn("const s =", sig)
        self.assertNotIn("helper()", sig)
        self.assertIn("export class Repo extends Base { … }", sig)
        self.assertIn("async find(id: string): Promise<User | null> { … }", sig)
        self.assertNotIn("#internal", sig)
        self.assertNotIn("if (id)", sig)
        self.assertIn('export { helper as h } from "./h";', sig)
        self.assertIn("export const LIMIT = 10;", sig)

    def test_go_rust_java_csharp(self):
        go = write(self.tmp, "a.go", '''
            package a
            type Server struct {
                Addr string
            }
            func (s *Server) Handle(w http.ResponseWriter,
                r *http.Request) error {
                return nil
            }
        ''')
        g = fgh.extract_signatures(go)
        self.assertIn("Addr string", g)
        self.assertIn("r *http.Request) error { … }", g)
        self.assertNotIn("return nil", g)

        rs = write(self.tmp, "a.rs", '''
            pub struct Cfg { pub port: u16 }
            impl Cfg {
                pub fn new(port: u16) -> Self { Self { port } }
                fn private(&self) {}
            }
        ''')
        r = fgh.extract_signatures(rs)
        self.assertIn("pub port: u16", r)
        self.assertIn("pub fn new(port: u16) -> Self { … }", r)
        self.assertNotIn("fn private", r)

        cs = write(self.tmp, "a.cs", '''
            namespace App
            {
                public class OrderService : IOrderService
                {
                    public async Task<Order> GetAsync(Guid id)
                    {
                        return await _repo.Find(id);
                    }
                    private void Hidden() { }
                }
            }
        ''')
        c = fgh.extract_signatures(cs)
        self.assertIn("public class OrderService : IOrderService", c)
        self.assertIn("public async Task<Order> GetAsync(Guid id)", c)
        self.assertNotIn("Hidden", c)
        self.assertNotIn("_repo", c)

    def test_sql_and_hcl(self):
        sql = write(self.tmp, "a.sql", '''
            CREATE TABLE users (
              id BIGINT PRIMARY KEY,
              email TEXT NOT NULL
            );
            CREATE OR REPLACE VIEW active AS
            SELECT * FROM users WHERE active;
        ''')
        s = fgh.extract_signatures(sql)
        self.assertIn("email TEXT NOT NULL", s)
        self.assertIn("CREATE OR REPLACE VIEW active AS", s)
        self.assertNotIn("SELECT", s)
        tf = write(self.tmp, "a.tf", '''
            variable "region" {
              type = string
            }
            resource "aws_s3_bucket" "b" {
              bucket = "x"
            }
        ''')
        t = fgh.extract_signatures(tf)
        self.assertIn("type = string", t)
        self.assertIn('resource "aws_s3_bucket" "b" { … }', t)
        self.assertNotIn('bucket = "x"', t)

    def test_truncation(self):
        p = write(self.tmp, "big.py", "\n".join(f"def f{i}(): ..." for i in range(300)))
        self.assertIn("truncated", fgh.extract_signatures(p, max_lines=20))


class BriefTests(unittest.TestCase):
    def test_fence_escapes_backticks(self):
        f = fgh.fence("a ``` b ```` c")
        self.assertTrue(f.startswith("`````"))

    def test_brief_sections_and_scrub(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = pathlib.Path(d)
            contracts = write(tmp, "t.ts", "export interface A { x: number }\n")
            anchor = write(tmp, "s.ts", "\n".join(f"line{i}" for i in range(1, 41)))
            text = fgh.build_brief(
                goal="Implement A",
                own=["src/a.ts"],
                verify="npx tsc --noEmit && npx vitest run",
                contracts=[str(contracts)],
                anchor=f"{anchor}:5-9",
                decisions=["no throws"],
                edges=["empty"],
                context=["key sk-proj-abcdefghijklmnopqrstuvwxyz123456"],
            )
        for section in ("[FGH-WORKER]", "## Goal", "## Files you own", "## Decisions", "## Contracts",
                        "## Style anchor", "## Edge cases", "## Verify", "## Report"):
            self.assertIn(section, text)
        self.assertIn("line5", text)
        self.assertIn("line9", text)
        self.assertNotIn("line10", text)
        self.assertIn("&&", text)
        self.assertNotIn("sk-proj-abcdefghij", text)

    def test_brief_requires_verify_and_files(self):
        with self.assertRaises(ValueError):
            fgh.build_brief("g", ["a"], "")
        with self.assertRaises(ValueError):
            fgh.build_brief("g", [], "pytest")

    def test_anchor_windows_path(self):
        path, s, e = fgh.parse_anchor(r"C:\repo\src\a.ts:10-12")
        self.assertEqual(str(path), r"C:\repo\src\a.ts")
        self.assertEqual((s, e), (10, 12))
        _, s2, e2 = fgh.parse_anchor("a.ts:1-100")
        self.assertEqual(e2 - s2, 19)  # capped at 20 lines


class ScrubTests(unittest.TestCase):
    SECRETS = {
        "aws-key": "AKIAABCDEFGHIJKLMNOP",
        "github-token": "ghp_" + "a" * 36,
        "openai-anthropic-key": "sk-ant-" + "b" * 30,
        "google-key": "AIza" + "c" * 35,
        "slack-token": "xoxb-1234567890-abcdef",
        "jwt": "eyJhbGciOiJIUzI1.eyJzdWIiOiIxMjM0.SflKxwRJSMeKKF2QT4",
    }

    def test_each_secret_kind(self):
        for kind, secret in self.SECRETS.items():
            out, counts = fgh.scrub(f"value = {secret} end")
            self.assertNotIn(secret, out, kind)
            self.assertIn(kind, counts, kind)

    def test_private_key_url_env_quoted(self):
        pk = "-----BEGIN RSA PRIVATE KEY-----\nMIIabc\n-----END RSA PRIVATE KEY-----"
        self.assertNotIn("MIIabc", fgh.scrub(pk)[0])
        out = fgh.scrub("postgres://admin:hunter22@db:5432/x")[0]
        self.assertNotIn("hunter22", out)
        self.assertIn("admin:", out)
        out = fgh.scrub("DATABASE_PASSWORD=supersecret1\nexport API_KEY='abcdef123456'")[0]
        self.assertNotIn("supersecret1", out)
        self.assertNotIn("abcdef123456", out)
        out = fgh.scrub('config = {"api_key": "zzzzzzzzzzzz"}')[0]
        self.assertNotIn("zzzzzzzzzzzz", out)

    def test_no_false_positives(self):
        code = ("task-runner sketch skeleton token_count = count_tokens(text)\n"
                "password = hash_password(raw)\nconst desk = 'sk-short';\n")
        out, counts = fgh.scrub(code)
        self.assertEqual(out, code)
        self.assertEqual(counts, {})


class LedgerTests(unittest.TestCase):
    def test_record_stats_demotion_and_corruption(self):
        with tempfile.TemporaryDirectory() as d:
            path = pathlib.Path(d) / "sub" / "ledger.jsonl"
            for i in range(6):
                fgh.ledger_record(path, "L3", f"t{i}", i == 0, gateway="ollama")
            for i in range(5):
                fgh.ledger_record(path, "L2", f"w{i}", True)
            with path.open("a", encoding="utf-8") as fh:
                fh.write("{corrupt\n\n[1,2]\n")
            stats = fgh.ledger_stats(fgh.ledger_read(path), CFG)
        self.assertTrue(stats["ollama"]["demoted"])
        self.assertEqual(stats["ollama"]["runs_total"], 6)
        self.assertFalse(stats["L2"]["demoted"])

    def test_missing_ledger(self):
        self.assertEqual(fgh.ledger_read(pathlib.Path("does/not/exist.jsonl")), [])


class ExternalTests(unittest.TestCase):
    GOOD = "[FGH-WORKER]\n## Goal\nWrite tests\n## Verify\n```bash\npytest -q\n```\n"

    def cfg(self, **ext):
        c = fgh.deep_merge(CFG, {"external": ext}) if ext else CFG
        return c

    def test_policy(self):
        self.assertIsNone(fgh.external_policy(self.GOOD, self.cfg(), {}, None, "auto"))
        self.assertIn("high-risk", fgh.external_policy(self.GOOD, self.cfg(), {}, None, "high"))
        risky = self.GOOD.replace("Write tests", "Write the payment refund flow")
        self.assertIn("high-risk", fgh.external_policy(risky, self.cfg(), {}, None, "auto"))
        no_verify = "## Goal\nx\n## Verify\n```bash\nnone\n```\n"
        self.assertIn("verify", fgh.external_policy(no_verify, self.cfg(), {}, None, "auto"))
        self.assertIn("demoted", fgh.external_policy(self.GOOD, self.cfg(), {"ollama": {"demoted": True}}, "ollama", "auto"))
        self.assertIn("disabled", fgh.external_policy(self.GOOD, self.cfg(enabled=False), {}, None, "auto"))

    def test_gateway_selection(self):
        gws = [
            {"name": "remote", "base_url": "http://r/v1", "local": False},
            {"name": "local1", "base_url": "http://l1/v1", "local": True},
            {"name": "local2", "base_url": "http://l2/v1", "local": True},
        ]
        cfg = self.cfg(gateways=gws)
        up = lambda names: (lambda g: g["name"] in names)  # noqa: E731
        self.assertEqual(fgh.select_gateway(cfg, {}, None, up({"remote", "local2"}))["name"], "local2")
        self.assertEqual(fgh.select_gateway(cfg, {}, None, up({"remote"}))["name"], "remote")
        self.assertIsNone(fgh.select_gateway(self.cfg(gateways=gws, privacy="local_only"), {}, None, up({"remote"})))
        self.assertIsNone(fgh.select_gateway(self.cfg(gateways=gws, allow_remote=False), {}, None, up({"remote"})))
        self.assertEqual(fgh.select_gateway(cfg, {"local2": {"demoted": True}}, None, up({"local2", "remote"}))["name"], "remote")
        self.assertEqual(fgh.select_gateway(cfg, {}, "remote", up({"remote", "local1"}))["name"], "remote")

    def test_extract_code(self):
        content = "FILE: a.py\n```python\nprint(1)\n```\nFILE: b.py\n````python\nx = '```'\n````\n"
        self.assertEqual(fgh.extract_code(content), "print(1)\nx = '```'\n")
        self.assertEqual(fgh.extract_code("plain"), "plain")


class ConfigAndInstallTests(unittest.TestCase):
    def test_deep_merge(self):
        merged = fgh.deep_merge({"a": {"b": 1, "c": 2}, "l": [1]}, {"a": {"c": 3}, "l": [2]})
        self.assertEqual(merged, {"a": {"b": 1, "c": 3}, "l": [2]})

    def test_default_config_is_valid(self):
        data = json.loads(fgh.DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))
        self.assertEqual(data["version"], fgh.VERSION)
        for key in ("switches", "routing", "high_risk_keywords", "external", "ledger"):
            self.assertIn(key, data)

    def test_upsert_rule_idempotent_and_legacy(self):
        with tempfile.TemporaryDirectory() as d:
            f = pathlib.Path(d) / "GEMINI.md"
            f.write_text("# My rules\nkeep me\n", encoding="utf-8")
            self.assertEqual(fgh.upsert_rule(f, "RULE v1"), "appended")
            self.assertEqual(fgh.upsert_rule(f, "RULE v2"), "updated")
            text = f.read_text(encoding="utf-8")
            self.assertIn("keep me", text)
            self.assertIn("RULE v2", text)
            self.assertNotIn("RULE v1", text)
            self.assertEqual(text.count(fgh.RULE_BEGIN), 1)

            legacy = pathlib.Path(d) / "L.md"
            legacy.write_text("# Global Quota-Preserving Adaptive Delegator Rule (x)\nold\n", encoding="utf-8")
            self.assertTrue(fgh.upsert_rule(legacy, "NEW").startswith("legacy-found"))
            self.assertTrue(fgh.upsert_rule(legacy, "NEW", replace_legacy=True).startswith("replaced-legacy"))
            self.assertNotIn("old", legacy.read_text(encoding="utf-8"))
            self.assertTrue((pathlib.Path(d) / "L.md.bak").is_file())

    def test_install_global_into_temp_home(self):
        with tempfile.TemporaryDirectory() as d:
            res = fgh.install("global", None, replace_legacy=False, dry_run=False, home=pathlib.Path(d))
            dest = pathlib.Path(res["skill"])
            self.assertTrue((dest / "SKILL.md").is_file())
            self.assertTrue((dest / "scripts" / "fgh.py").is_file())
            self.assertFalse(any(dest.rglob("__pycache__")))
            self.assertIn(fgh.RULE_BEGIN, pathlib.Path(res["rule_file"]).read_text(encoding="utf-8"))


class CliTests(unittest.TestCase):
    def test_route_cli_exit_codes(self):
        self.assertEqual(fgh.main(["route", "--kind", "generate", "--lines", "10", "--files", "1"]), 0)
        self.assertEqual(fgh.main(["route", "--kind", "generate", "--lines", "-5"]), 2)


if __name__ == "__main__":
    unittest.main()
