#!/usr/bin/env python3
"""Deterministic node lifecycle CLI; Python standard library only."""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from mesh_runtime import append_journal, read_journal

PLANES = {"contract-plane", "ingress-plane", "compute-plane", "provenance-plane", "control-plane", "tooling-plane"}
HEX40 = re.compile(r"^[0-9a-f]{40}$")


def wal_path(root: Path) -> Path:
    return Path(root) / ".runtime" / "wal.jsonl"


def append_checkpoint(root, step, status, artifact=None, note=""):
    if status not in {"PENDING", "COMMITTED", "FAILED"}:
        raise ValueError("invalid checkpoint status")
    if not isinstance(step, str) or not step.strip():
        raise ValueError("step must be non-empty")
    return append_journal(wal_path(Path(root)), {
        "timestamp": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        "step": step, "status": status, "artifact": artifact, "note": note,
    })


def _major(version: str) -> int:
    if not isinstance(version, str) or not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError("schema_version must be strict semantic version X.Y.Z")
    return int(version.split(".", 1)[0])


def topological_sort(lock):
    satellites = lock.get("satellites", [])
    if not isinstance(satellites, list):
        raise ValueError("mesh.lock satellites must be an array")
    graph = {}
    for item in satellites:
        if not isinstance(item, dict) or not isinstance(item.get("node_id"), str):
            raise ValueError("each dependency requires a node_id")
        node_id = item["node_id"]
        if node_id in graph:
            raise ValueError(f"duplicate dependency node_id: {node_id}")
        if not isinstance(item.get("uri"), str) or not item["uri"].startswith("https://"):
            raise ValueError(f"dependency {node_id} must use an HTTPS repository URI")
        if not isinstance(item.get("version"), str) or not item["version"].strip():
            raise ValueError(f"dependency {node_id} must declare a release identifier")
        if not isinstance(item.get("commit"), str) or not HEX40.fullmatch(item["commit"]):
            raise ValueError(f"dependency {node_id} must pin a full 40-character commit SHA")
        if not isinstance(item.get("depends_on", []), list) or any(not isinstance(dep, str) or not dep for dep in item.get("depends_on", [])):
            raise ValueError(f"dependency {node_id} has invalid depends_on")
        graph[node_id] = item.get("depends_on", [])
    state, ordered = {}, []

    def visit(node):
        if node not in graph:
            raise ValueError(f"missing dependency: {node}")
        if state.get(node) == 1:
            raise ValueError(f"dependency cycle detected at {node}")
        if state.get(node) == 2:
            return
        state[node] = 1
        for dependency in sorted(graph[node]):
            visit(dependency)
        state[node] = 2
        ordered.append(node)

    for node in sorted(graph):
        visit(node)
    return ordered, graph


def verify(root):
    root = Path(root)
    meta_path = root / ".mesh-node.json"
    if not meta_path.is_file():
        raise ValueError("missing .mesh-node.json")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    if _major(meta.get("schema_version")) != 1:
        raise ValueError("unsupported mesh-node schema major version")
    required = ("node_id", "namespace", "visibility", "tier", "plane", "parent")
    missing = [key for key in required if key not in meta]
    if missing:
        raise ValueError("missing node fields: " + ", ".join(missing))
    if not all(isinstance(meta[key], str) and meta[key].strip() for key in ("node_id", "namespace")):
        raise ValueError("node_id and namespace must be non-empty strings")
    if meta["visibility"] not in {"private", "public"}:
        raise ValueError("invalid visibility")
    if type(meta["tier"]) is not int or not 1 <= meta["tier"] <= 4:
        raise ValueError("tier must be integer 1..4")
    if meta["plane"] not in PLANES:
        raise ValueError("invalid architectural plane")
    if "architectural_plane" in meta and meta["architectural_plane"] != meta["plane"]:
        raise ValueError("architectural_plane and legacy plane disagree")
    dependencies = meta.get("depends_on", [])
    if not isinstance(dependencies, list) or any(not isinstance(x, str) or not x for x in dependencies):
        raise ValueError("depends_on must be an array of non-empty node identifiers")
    order, graph = [], {}
    lock_path = root / "mesh.lock"
    if dependencies and not lock_path.is_file():
        raise ValueError("node declares dependencies but mesh.lock is missing")
    if lock_path.exists():
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
        if _major(lock.get("schema_version")) != 1:
            raise ValueError("unsupported mesh.lock schema major version")
        order, graph = topological_sort(lock)
        if set(dependencies) != set(graph):
            raise ValueError("mesh-node depends_on does not match pinned mesh.lock dependencies")
    summon_path = root / "summon.lock"
    if not summon_path.is_file():
        raise ValueError("missing summon.lock")
    summon = json.loads(summon_path.read_text(encoding="utf-8"))
    if _major(summon.get("schema_version")) != 1:
        raise ValueError("unsupported summon.lock schema major version")
    if summon.get("depends_on", []) != dependencies:
        raise ValueError("summon.lock depends_on does not match .mesh-node.json")
    if not isinstance(summon.get("env_defaults", {}), dict):
        raise ValueError("summon.lock env_defaults must be an object")
    if not isinstance(summon.get("bootstrap_commands", []), list):
        raise ValueError("summon.lock bootstrap_commands must be an array")
    if not isinstance(summon.get("healthcheck_command"), list) or not summon["healthcheck_command"]:
        raise ValueError("summon.lock requires a non-empty healthcheck_command")
    journal = read_journal(wal_path(root))
    return {"node_id": meta["node_id"], "tier": meta["tier"], "dependency_order": order, "wal_entries": len(journal)}


def do_init(args):
    root = Path(args.path)
    root.mkdir(parents=True, exist_ok=True)
    (root / ".runtime").mkdir(exist_ok=True)
    hierarchy = {1: "standalone", 2: "satellite", 3: "federated", 4: "domain-umbrella"}[args.tier]
    meta = {
        "schema_version": "1.0.0", "node_id": args.node_id, "namespace": args.namespace,
        "visibility": args.visibility, "hierarchy_tier": hierarchy,
        "architectural_plane": args.plane, "tier": args.tier, "plane": args.plane,
        "parent": args.parent or None, "depends_on": [],
    }
    (root / ".mesh-node.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    lock = {"schema_version": "1.0.0", "depends_on": [], "env_defaults": {}, "bootstrap_commands": [],
            "healthcheck_command": [sys.executable, "-c", "print('healthcheck: ok')"]}
    (root / "summon.lock").write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"initialized": str(root), "node_id": args.node_id}, sort_keys=True))
    return 0


def do_checkpoint(args):
    entry = append_checkpoint(args.path, args.step, args.status, args.artifact, args.note)
    print(json.dumps({"sequence": entry["sequence"], "entry_hash": entry["entry_hash"]}, sort_keys=True))
    return 0


def do_resume(args):
    entries = read_journal(wal_path(Path(args.path)))
    committed = [entry for entry in entries if entry["status"] == "COMMITTED"]
    resolved = {entry["step"] for entry in entries if entry["status"] == "COMMITTED"}
    pending = {entry["step"] for entry in entries if entry["status"] == "PENDING" and entry["step"] not in resolved}
    failed = {entry["step"] for entry in entries if entry["status"] == "FAILED" and entry["step"] not in resolved}
    print(json.dumps({"entries": len(entries), "last_committed": committed[-1]["step"] if committed else None,
                      "pending_replay": sorted(pending), "failed_steps": sorted(failed),
                      "replay_mode": "plan-only; commands are never replayed automatically"}, sort_keys=True))
    return 0


def _run_bounded(command, root, env, timeout):
    if not isinstance(command, list) or not command or any(not isinstance(arg, str) for arg in command):
        raise ValueError("commands must be non-empty argv arrays of strings")
    return subprocess.run(command, cwd=root, env=env, check=True, timeout=timeout, shell=False)


def do_summon(args):
    root = Path(args.path).resolve()
    lock_path = root / "summon.lock"
    if not lock_path.is_file():
        raise ValueError("missing summon.lock")
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    if _major(lock.get("schema_version")) != 1:
        raise ValueError("unsupported summon.lock schema major version")
    commands = lock.get("bootstrap_commands", [])
    health = lock.get("healthcheck_command")
    if not isinstance(commands, list) or not isinstance(health, list) or not health:
        raise ValueError("summon.lock requires bootstrap_commands and healthcheck_command")
    env = os.environ.copy()
    for key, value in lock.get("env_defaults", {}).items():
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", str(key)):
            raise ValueError(f"invalid environment variable name: {key!r}")
        env.setdefault(str(key), str(value))
    plan = {"bootstrap_commands": commands, "healthcheck_command": health, "timeout_seconds": args.timeout}
    if not args.execute:
        print(json.dumps({"dry_run": True, "plan": plan}, sort_keys=True))
        return 0
    for index, command in enumerate(commands, 1):
        step = f"summon-bootstrap-{index}"
        append_checkpoint(root, step, "PENDING", note="bootstrap command started")
        try:
            _run_bounded(command, root, env, args.timeout)
        except subprocess.TimeoutExpired:
            append_checkpoint(root, step, "FAILED", note="bootstrap command timed out")
            raise ValueError(f"{step} exceeded {args.timeout} seconds")
        except subprocess.CalledProcessError as exc:
            append_checkpoint(root, step, "FAILED", note=f"exit status {exc.returncode}")
            raise
        append_checkpoint(root, step, "COMMITTED", note="bootstrap command completed")
    append_checkpoint(root, "summon-healthcheck", "PENDING", note="health check started")
    try:
        _run_bounded(health, root, env, args.timeout)
    except subprocess.TimeoutExpired:
        append_checkpoint(root, "summon-healthcheck", "FAILED", note="health check timed out")
        raise ValueError(f"health check exceeded {args.timeout} seconds")
    except subprocess.CalledProcessError as exc:
        append_checkpoint(root, "summon-healthcheck", "FAILED", note=f"exit status {exc.returncode}")
        raise
    append_checkpoint(root, "summon-healthcheck", "COMMITTED", note="health check passed")
    print(json.dumps({"summoned": str(root), "healthcheck": "passed"}, sort_keys=True))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("init")
    p.add_argument("path"); p.add_argument("--node-id", required=True); p.add_argument("--namespace", required=True)
    p.add_argument("--visibility", choices=["private", "public"], required=True); p.add_argument("--tier", type=int, choices=range(1, 5), required=True)
    p.add_argument("--plane", choices=sorted(PLANES), required=True); p.add_argument("--parent", default="")
    p.set_defaults(func=do_init)
    p = sub.add_parser("checkpoint"); p.add_argument("path"); p.add_argument("--step", required=True)
    p.add_argument("--status", choices=["PENDING", "COMMITTED", "FAILED"], required=True); p.add_argument("--artifact"); p.add_argument("--note", default="")
    p.set_defaults(func=do_checkpoint)
    p = sub.add_parser("resume"); p.add_argument("path"); p.set_defaults(func=do_resume)
    p = sub.add_parser("summon"); p.add_argument("path"); p.add_argument("--execute", action="store_true", help="execute reviewed commands; default is dry-run")
    p.add_argument("--timeout", type=float, default=60.0); p.set_defaults(func=do_summon)
    p = sub.add_parser("verify"); p.add_argument("path"); p.set_defaults(func=lambda a: (print(json.dumps(verify(a.path), sort_keys=True)) or 0))
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (OSError, ValueError, KeyError, json.JSONDecodeError, subprocess.CalledProcessError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
