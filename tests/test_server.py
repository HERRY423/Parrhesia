import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


def request(method, params=None, id=1):
    return {"jsonrpc": "2.0", "id": id, "method": method, "params": params or {}}


INITIALIZE = request("initialize", {"protocolVersion": "2025-11-25", "clientInfo": {"name": "integration-test", "version": "1"}, "capabilities": {}})


class MCPTests(unittest.TestCase):
    def exchange(self, workspace, messages):
        source = "\n".join(json.dumps(m, ensure_ascii=False) if not isinstance(m, str) else m for m in messages) + "\n"
        result = subprocess.run([sys.executable, "-m", "parrhesia", "serve", "--workspace", str(workspace)], input=source.encode("utf-8"), cwd=ROOT, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", errors="replace"))
        return [json.loads(line) for line in result.stdout.splitlines()]

    def test_real_process_handshake_contract_and_utf8(self):
        with tempfile.TemporaryDirectory() as workspace:
            responses = self.exchange(workspace, [INITIALIZE, {"jsonrpc": "2.0", "method": "notifications/initialized"}, request("tools/list", id=2), request("tools/call", {"name": "parrhesia_contract"}, 3), request("tools/call", {"name": "parrhesia_workflow", "arguments": {"action": "create_case", "payload": {"question": "这项证据支持什么？", "draft": "中文草稿"}}}, 4)])
            self.assertEqual(len(responses), 4)
            self.assertEqual(responses[0]["result"]["protocolVersion"], "2025-11-25")
            self.assertEqual(len(responses[1]["result"]["tools"]), 3)
            self.assertIn("submit_adjudication", responses[2]["result"]["structuredContent"]["contract"])
            self.assertFalse(responses[3]["result"]["isError"])
            case_id = responses[3]["result"]["structuredContent"]["case_id"]
            restart = self.exchange(workspace, [INITIALIZE, request("tools/call", {"name": "parrhesia_workflow", "arguments": {"action": "get_case", "payload": {"case_id": case_id}}}, 2)])
            self.assertIn("中文草稿", json.dumps(restart[1], ensure_ascii=False))

    def test_invalid_frames_do_not_kill_process_or_mutate(self):
        with tempfile.TemporaryDirectory() as workspace:
            responses = self.exchange(workspace, ["invalid-json", INITIALIZE, request("tools/call", {"name": "parrhesia_workflow", "arguments": {"action": "not-an-action", "payload": {}}}, 2), {"jsonrpc": "2.0", "method": "tools/call", "params": {"name": "parrhesia_select_workspace", "arguments": {"path": "C:/"}}}, request("tools/call", {"name": "parrhesia_contract"}, 3)])
            self.assertEqual(responses[0]["error"]["code"], -32700)
            self.assertTrue(responses[2]["result"]["isError"])
            self.assertEqual(Path(responses[3]["result"]["structuredContent"]["workspace"]), Path(workspace).resolve())

    def test_workspace_selection_and_error_boundaries(self):
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            responses = self.exchange(first, [request("tools/list"), INITIALIZE, request("tools/call", {"name": "parrhesia_select_workspace", "arguments": {"path": "relative"}}, 2), request("tools/call", {"name": "parrhesia_select_workspace", "arguments": {"path": second}}, 3), request("resources/read", {"uri": "parrhesia://contract"}, 4), request("tools/call", {"name": "unknown"}, 5)])
            self.assertEqual(responses[0]["error"]["code"], -32002)
            self.assertTrue(responses[2]["result"]["isError"])
            self.assertEqual(Path(responses[3]["result"]["structuredContent"]["workspace"]), Path(second).resolve())
            self.assertIn("Lifecycle", responses[4]["result"]["contents"][0]["text"])
            self.assertEqual(responses[5]["error"]["code"], -32602)


if __name__ == "__main__":
    unittest.main()
