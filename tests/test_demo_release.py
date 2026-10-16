import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile


ROOT = Path(__file__).resolve().parents[1]


class DemoReleaseTests(unittest.TestCase):
    def test_demo_complete_and_existing_directory_preserved(self):
        from parrhesia.demo import run_demo
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "demo"
            result = run_demo(output)
            self.assertTrue(result["restart_recovery"])
            self.assertEqual(result["grok_behavior_improvement"], "not_measured")
            transcript = json.loads((output / "workflow-transcript.json").read_text(encoding="utf-8"))
            self.assertEqual(transcript[-1]["action"], "export")
            self.assertEqual(len([row for row in transcript if row["action"] == "submit_review"]), 2)
            self.assertTrue(Path(result["markdown"]).is_file())
            html = Path(result["html"]).read_text(encoding="utf-8")
            self.assertIn("人工构造的工程演示", html)
            self.assertIn('data-verdict="insufficient_evidence"', html)
            with self.assertRaises(ValueError):
                run_demo(output)

    def test_report_escapes_untrusted_draft(self):
        from parrhesia.report import render_report
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "report.html"
            render_report({"case_id": "x", "claims": [], "decisions": [], "findings": {}, "dispositions": [], "verification": {}, "export": {}, "draft": "<script>alert(1)</script>"}, path)
            content = path.read_text(encoding="utf-8")
            self.assertNotIn("<script>alert(1)</script>", content)
            self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", content)

    def test_report_preserves_judgment_and_partial_disposition_conditions(self):
        from parrhesia.demo import run_demo
        from parrhesia.report import render_report
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "demo"
            result = run_demo(output)
            calls = json.loads((output / "workflow-transcript.json").read_text(encoding="utf-8"))
            ledger = next(row["payload"]["claims"] for row in calls if row["action"] == "set_ledger")
            adjudication = next(row["payload"] for row in calls if row["action"] == "submit_adjudication")
            adjudication["decisions"][0]["verdict"] = "partially_supported"
            adjudication["decisions"][0]["condition"] = "仅在条件 <A> 成立时"
            adjudication["dispositions"][0].update({"disposition": "partial", "condition": "只采纳条件 <B> 的部分"})
            data = {"case_id": result["case_id"], "draft": "demo", "claims": ledger, "decisions": adjudication["decisions"], "dispositions": adjudication["dispositions"], "findings": {row["payload"]["role"]: row["payload"]["findings"] for row in calls if row["action"] == "submit_review"}, "verification": {}, "export": {}}
            path = output / "conditional-report.html"
            render_report(data, path)
            content = path.read_text(encoding="utf-8")
            self.assertIn("仅在条件 &lt;A&gt; 成立时", content)
            self.assertIn("只采纳条件 &lt;B&gt; 的部分", content)

    def test_release_extracts_and_starts_without_source_checkout(self):
        spec = importlib.util.spec_from_file_location("build_release", ROOT / "scripts" / "build-release.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            archive_path = base / "plugin.zip"
            result = module.build(archive_path)
            self.assertEqual(result, module.build(archive_path))
            package = base / "unpacked"
            with zipfile.ZipFile(archive_path) as archive:
                names = archive.namelist()
                self.assertTrue(all(not n.startswith(("artifacts/", "dist/", ".parrhesia/")) for n in names))
                archive.extractall(package)
            manifest = json.loads((package / "RELEASE-MANIFEST.json").read_text(encoding="utf-8"))
            for name, metadata in manifest["files"].items():
                self.assertEqual(hashlib.sha256((package / name).read_bytes()).hexdigest(), metadata["sha256"])
            init = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-11-25", "clientInfo": {"name": "extract-test", "version": "1"}, "capabilities": {}}}
            contract = {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "parrhesia_contract", "arguments": {}}}
            result = subprocess.run([sys.executable, str(package / "scripts" / "run-mcp.py"), "--default-workspace", str(base / "state")], input="\n".join(map(json.dumps, [init, contract])) + "\n", text=True, encoding="utf-8", cwd=base, capture_output=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            messages = [json.loads(line) for line in result.stdout.splitlines()]
            self.assertFalse(messages[1]["result"]["isError"])
            self.assertIn("submit_adjudication", messages[1]["result"]["structuredContent"]["contract"])


if __name__ == "__main__":
    unittest.main()
