"""Machine-native task validation and deterministic result envelopes."""
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import PurePosixPath

PROTOCOL = "mesh-archivist-agent/1"
OPERATIONS = {"inspect", "plan", "verify", "checkpoint", "summon", "crawl", "promote", "mutate"}
PLANES = {"contract-plane", "ingress-plane", "compute-plane", "provenance-plane", "control-plane", "tooling-plane"}
REQUIRED = {"protocol", "task_id", "origin_namespace", "target_node", "requested_plane", "operation", "scope", "inputs_sha256", "expected_contract", "expires_at", "approval_ref"}
HEX64 = re.compile(r"^[0-9a-f]{64}$")
def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
def validate_task(envelope, known_nodes, now=None):
    if not isinstance(envelope, dict): raise ValueError("task envelope must be an object")
    missing=REQUIRED-set(envelope)
    if missing: raise ValueError("missing task fields: "+", ".join(sorted(missing)))
    extra=set(envelope)-REQUIRED
    if extra: raise ValueError("unknown task fields: "+", ".join(sorted(extra)))
    if envelope["protocol"] != PROTOCOL: raise ValueError("unsupported protocol version")
    if not isinstance(envelope["task_id"],str) or not envelope["task_id"].strip(): raise ValueError("task_id must be non-empty")
    if envelope["target_node"] not in set(known_nodes): raise ValueError("target node is not declared")
    if envelope["requested_plane"] not in PLANES: raise ValueError("unknown architectural plane")
    if envelope["operation"] not in OPERATIONS: raise ValueError("unsupported operation")
    if not isinstance(envelope["scope"],list) or not envelope["scope"] or any(not isinstance(x,str) or not x.strip() for x in envelope["scope"]): raise ValueError("scope must be a non-empty list of explicit paths")
    for item in envelope["scope"]:
        path=PurePosixPath(item)
        if path.is_absolute() or ".." in path.parts or "\\" in item: raise ValueError("scope path escapes the repository boundary")
    if not isinstance(envelope["inputs_sha256"],str) or not HEX64.fullmatch(envelope["inputs_sha256"]): raise ValueError("inputs_sha256 must be a lowercase SHA-256 digest")
    try:
        expiry=datetime.fromisoformat(envelope["expires_at"].replace("Z", "+00:00"))
        if expiry.tzinfo is None: raise ValueError("expires_at must include a timezone")
    except (AttributeError,TypeError,ValueError) as exc: raise ValueError("expires_at must be an RFC3339 timestamp with timezone") from exc
    current=now or datetime.now(timezone.utc)
    if expiry <= current: raise ValueError("task envelope has expired")
    if envelope["operation"] == "mutate":
        approval=envelope["approval_ref"]
        if not isinstance(approval,dict): raise ValueError("mutation requires an approval object")
        expected={"target_node":envelope["target_node"],"operation":"mutate","inputs_sha256":envelope["inputs_sha256"]}
        if any(approval.get(k)!=v for k,v in expected.items()): raise ValueError("approval is not bound to this target and input digest")
    return dict(envelope)
def capability_manifest():
    return {"protocol":PROTOCOL,"runtime":"Python 3.11+ standard library","operations":sorted(OPERATIONS),"read_only_by_default":True,"mutation_requires_bound_approval":True,"network_access":"caller-controlled; not performed by protocol adapter","approval_verification":"binding-only; caller must authenticate approval signatures","deterministic_serialization":"sorted JSON keys and compact separators"}
def build_result(task, node_id, status, result, evidence=None, limitations=None, next_action="none"):
    if status not in {"completed","blocked","rejected","failed"}: raise ValueError("invalid result status")
    raw=canonical(result).encode("utf-8")
    return {"protocol":PROTOCOL,"task_id":task["task_id"],"node_id":node_id,"status":status,"result_sha256":hashlib.sha256(raw).hexdigest(),"evidence":list(evidence or []),"limitations":list(limitations or []),"next_action":next_action}
