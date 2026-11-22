"""Machine-native task validation and deterministic result envelopes."""
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import PurePosixPath

PROTOCOL = "mesh-archivist-agent/1"
OPERATIONS = {"inspect", "plan", "verify", "checkpoint", "summon", "crawl", "promote", "mutate"}
SIDE_EFFECTING = {"checkpoint", "summon", "crawl", "promote", "mutate"}
PLANES = {"contract-plane", "ingress-plane", "compute-plane", "provenance-plane", "control-plane", "tooling-plane"}
REQUIRED = {"protocol", "task_id", "origin_namespace", "target_node", "requested_plane", "operation", "scope", "inputs_sha256", "expected_contract", "expires_at", "approval_ref"}
HEX64 = re.compile(r"^[0-9a-f]{64}$")


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def validate_task(envelope, known_nodes, now=None, approval_verifier=None):
    if not isinstance(envelope, dict):
        raise ValueError("task envelope must be an object")
    missing = REQUIRED - set(envelope)
    if missing:
        raise ValueError("missing task fields: " + ", ".join(sorted(missing)))
    if set(envelope) - REQUIRED:
        raise ValueError("unknown task fields: " + ", ".join(sorted(set(envelope) - REQUIRED)))
    if envelope["protocol"] != PROTOCOL:
        raise ValueError("unsupported protocol version")
    if not isinstance(envelope["task_id"], str) or not envelope["task_id"].strip():
        raise ValueError("task_id must be non-empty")
    if not isinstance(envelope["target_node"], str) or envelope["target_node"] not in set(known_nodes):
        raise ValueError("target node is not declared")
    if envelope["requested_plane"] not in PLANES:
        raise ValueError("unknown architectural plane")
    operation = envelope["operation"]
    if operation not in OPERATIONS:
        raise ValueError("unsupported operation")
    scope = envelope["scope"]
    if not isinstance(scope, list) or not scope or any(not isinstance(item, str) or not item.strip() for item in scope):
        raise ValueError("scope must be a non-empty list of explicit paths")
    for item in scope:
        path = PurePosixPath(item)
        if path.is_absolute() or ".." in path.parts or "\\" in item:
            raise ValueError("scope path escapes the repository boundary")
    if not isinstance(envelope["inputs_sha256"], str) or not HEX64.fullmatch(envelope["inputs_sha256"]):
        raise ValueError("inputs_sha256 must be a lowercase SHA-256 digest")
    if not isinstance(envelope["expected_contract"], str) or not envelope["expected_contract"].strip():
        raise ValueError("expected_contract must be non-empty")
    try:
        expiry = datetime.fromisoformat(envelope["expires_at"].replace("Z", "+00:00"))
        if expiry.tzinfo is None:
            raise ValueError("timezone required")
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("expires_at must be an RFC3339 timestamp with timezone") from exc
    if expiry <= (now or datetime.now(timezone.utc)):
        raise ValueError("task envelope has expired")
    if operation in SIDE_EFFECTING:
        approval = envelope["approval_ref"]
        if not isinstance(approval, dict):
            raise ValueError(f"{operation} requires a bound approval reference")
        expected = {"target_node": envelope["target_node"], "operation": operation,
                    "inputs_sha256": envelope["inputs_sha256"]}
        if any(approval.get(key) != value for key, value in expected.items()):
            raise ValueError("approval is not bound to this target, operation, and input digest")
        if not isinstance(approval.get("approval_id"), str) or not approval["approval_id"].strip():
            raise ValueError("approval_id is required")
        if not callable(approval_verifier) or not approval_verifier(approval, envelope):
            raise ValueError("approval signature could not be authenticated by the host verifier")
    elif envelope["approval_ref"] is not None:
        raise ValueError("read-only operations must not carry an approval reference")
    return dict(envelope)


def capability_manifest():
    return {"protocol": PROTOCOL, "runtime": "Python 3.11+ standard library",
            "operations": sorted(OPERATIONS), "side_effecting_operations": sorted(SIDE_EFFECTING),
            "read_only_by_default": True, "approval_required_for_all_side_effects": True,
            "approval_verification": "host-provided cryptographic verifier is mandatory",
            "network_access": "caller-controlled; not performed by protocol adapter",
            "deterministic_serialization": "sorted JSON keys and compact separators"}


def build_result(task, node_id, status, result, evidence=None, limitations=None, next_action="none"):
    if status not in {"completed", "blocked", "rejected", "failed"}:
        raise ValueError("invalid result status")
    raw = canonical(result).encode("utf-8")
    return {"protocol": PROTOCOL, "task_id": task["task_id"], "node_id": node_id, "status": status,
            "result_sha256": hashlib.sha256(raw).hexdigest(), "evidence": list(evidence or []),
            "limitations": list(limitations or []), "next_action": next_action}
