#!/usr/bin/env python3
"""Deny-by-default public catalog projection and deterministic Merkle root."""
import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

ALLOW = {"namespace", "repository", "name", "description", "html_url", "default_branch", "visibility",
         "archived", "created_at", "updated_at", "pushed_at", "language", "topics", "planes",
         "stargazers_count", "forks_count", "clone_count_14d"}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def merkle(leaves):
    if not leaves:
        return sha(b"")
    level = [sha(item) for item in leaves]
    while len(level) > 1:
        if len(level) % 2:
            level.append(level[-1])
        level = [sha(bytes.fromhex(level[index]) + bytes.fromhex(level[index + 1]))
                 for index in range(0, len(level), 2)]
    return level[0]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--root-output", default="PUBLIC_LEDGER_MERKLE.txt")
    parser.add_argument("--approve-review", action="store_true",
                        help="confirm a human has reviewed this exact input and destination")
    args = parser.parse_args()
    if not args.approve_review:
        raise SystemExit("promotion blocked: inspect the source and pass --approve-review after human review")
    source = Path(args.input).resolve()
    output = Path(args.output).resolve()
    root_output = Path(args.root_output).resolve()
    if source in {output, root_output} or output == root_output:
        raise SystemExit("input, public output, and Merkle output must be distinct paths")
    records, redacted = [], 0
    for line_number, line in enumerate(source.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        item = json.loads(line)
        if not isinstance(item, dict):
            raise ValueError(f"catalog line {line_number} must be an object")
        if item.get("private") is True or str(item.get("visibility", "")).lower() != "public":
            redacted += 1
            continue
        public = {key: item[key] for key in sorted(ALLOW) if key in item}
        if not public.get("repository") or not public.get("namespace"):
            redacted += 1
            continue
        records.append(public)
    records.sort(key=lambda row: (str(row.get("namespace", "")), str(row.get("repository", ""))))
    leaves = [canonical(record).encode("utf-8") for record in records]
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as stream:
        for record in records:
            stream.write(canonical(record) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    root = merkle(leaves)
    root_output.parent.mkdir(parents=True, exist_ok=True)
    with root_output.open("w", encoding="utf-8") as stream:
        stream.write(f"algorithm=sha256-merkle-v1\nroot={root}\nrecords={len(records)}\nredacted={redacted}\n")
        stream.flush()
        os.fsync(stream.fileno())
    print(json.dumps({"public_records": len(records), "redacted_records": redacted, "merkle_root": root}, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2)
