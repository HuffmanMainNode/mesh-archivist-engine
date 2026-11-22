import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE))
from mesh_runtime import append_journal, read_journal
from mesh_agent.protocol import PROTOCOL, validate_task


class SecurityHardeningTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def test_wal_truncated_tail_recovers_but_complete_corruption_fails(self):
        path = self.tmp / "wal.jsonl"
        append_journal(path, {"step": "one", "status": "PENDING"})
        with path.open("ab") as stream:
            stream.write(b'{"sequence":2,"partial":')
        entries = read_journal(path)
        self.assertEqual(len(entries), 1)
        self.assertTrue(path.read_bytes().endswith(b"\n"))
        with path.open("ab") as stream:
            stream.write(b'{"sequence":2,"step":"bad"}\n')
        with self.assertRaises(ValueError):
            read_journal(path)

    def test_concurrent_wal_appends_are_serialized(self):
        path = self.tmp / "concurrent.jsonl"
        code = ("import sys; from pathlib import Path; from mesh_runtime import append_journal; "
                "append_journal(Path(sys.argv[1]), {'step':sys.argv[2], 'status':'PENDING'})")
        processes = [subprocess.Popen([sys.executable, "-c", code, str(path), str(i)],
                                      env={**os.environ, "PYTHONPATH": str(ENGINE)}) for i in range(12)]
        self.assertTrue(all(process.wait() == 0 for process in processes))
        self.assertEqual(len(read_journal(path)), 12)

    def test_side_effect_requires_bound_authenticated_approval(self):
        from datetime import datetime, timezone, timedelta
        envelope = {
            "protocol": PROTOCOL, "task_id": "t1", "origin_namespace": "ns", "target_node": "node",
            "requested_plane": "tooling-plane", "operation": "crawl", "scope": ["."],
            "inputs_sha256": "a" * 64, "expected_contract": "1.0.0",
            "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
            "approval_ref": {"approval_id": "approval-1", "target_node": "node", "operation": "crawl",
                             "inputs_sha256": "a" * 64, "signature": "opaque"}
        }
        with self.assertRaisesRegex(ValueError, "authenticated"):
            validate_task(envelope, {"node"})
        checked = validate_task(envelope, {"node"}, approval_verifier=lambda approval, task: True)
        self.assertEqual(checked["operation"], "crawl")

    def test_private_and_missing_visibility_are_not_promoted(self):
        source, output, root = self.tmp / "source.jsonl", self.tmp / "public.jsonl", self.tmp / "root.txt"
        rows = [
            {"namespace": "ns", "repository": "public/repo", "visibility": "public", "private": False},
            {"namespace": "ns", "repository": "private/repo", "visibility": "private", "private": True},
            {"namespace": "ns", "repository": "unknown/repo", "private": False},
        ]
        source.write_text("".join(json.dumps(row) + "\n" for row in rows))
        result = subprocess.run([sys.executable, str(ENGINE / "diode_promote.py"), "--input", str(source),
                                 "--output", str(output), "--root-output", str(root), "--approve-review"],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("public/repo", output.read_text())
        self.assertNotIn("private/repo", output.read_text())
        self.assertNotIn("unknown/repo", output.read_text())

    def test_summon_is_dry_run_unless_execute_is_explicit(self):
        node = self.tmp / "node"
        subprocess.run([sys.executable, str(ENGINE / "meshctl.py"), "init", str(node),
                        "--node-id", "n", "--namespace", "ns", "--visibility", "private",
                        "--tier", "1", "--plane", "tooling-plane"], check=True, capture_output=True)
        marker = node / "executed.txt"
        (node / "summon.lock").write_text(json.dumps({
            "schema_version": "1.0.0", "env_defaults": {},
            "bootstrap_commands": [[sys.executable, "-c",
                                    f"from pathlib import Path; Path({str(marker)!r}).write_text('yes')"]],
            "healthcheck_command": [sys.executable, "-c", "print('ok')"]
        }))
        dry = subprocess.run([sys.executable, str(ENGINE / "meshctl.py"), "summon", str(node)],
                             capture_output=True, text=True)
        self.assertEqual(dry.returncode, 0, dry.stderr)
        self.assertFalse(marker.exists())
        execute = subprocess.run([sys.executable, str(ENGINE / "meshctl.py"), "summon", str(node), "--execute"],
                                 capture_output=True, text=True)
        self.assertEqual(execute.returncode, 0, execute.stderr)
        self.assertTrue(marker.exists())


if __name__ == "__main__":
    unittest.main()
