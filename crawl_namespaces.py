#!/usr/bin/env python3
"""Opt-in public-only GitHub namespace inventory crawler; standard library only."""
import argparse
import json
import os
import re
import sys
import tomllib
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from mesh_runtime import append_journal, read_journal

PLANES = {"contract-plane", "ingress-plane", "compute-plane", "provenance-plane", "control-plane", "tooling-plane"}
PLACEHOLDERS = {"primary-core-account", "standards-spec-account"}


def get_json(url, token, timeout=30.0):
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
               "User-Agent": "mesh-archivist-engine/1"}
    if token:
        headers["Authorization"] = "Bearer " + token
    request = Request(url, headers=headers)
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8")), response.headers


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="namespaces.toml")
    parser.add_argument("--output", default="ARCHIVAL_CATALOG.jsonl")
    parser.add_argument("--wal", default=".crawler-wal.jsonl")
    parser.add_argument("--api", default="https://api.github.com")
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args()
    if args.timeout <= 0:
        raise SystemExit("--timeout must be positive")
    config = tomllib.loads(Path(args.config).read_text(encoding="utf-8"))
    namespaces = config.get("namespaces", [])
    if not namespaces:
        raise SystemExit("no namespaces configured")
    for namespace in namespaces:
        handle = namespace.get("handle")
        kind = namespace.get("kind", "user")
        if not isinstance(handle, str) or not re.fullmatch(r"[A-Za-z0-9-]{1,39}", handle):
            raise SystemExit(f"invalid namespace handle: {handle!r}")
        if handle in PLACEHOLDERS:
            raise SystemExit("placeholder handles remain; configure real public namespaces manually")
        if kind not in {"user", "org"}:
            raise SystemExit(f"unsupported namespace kind: {kind!r}")
    token = os.environ.get("GITHUB_TOKEN")
    wal = Path(args.wal)
    done = {entry["repository"] for entry in read_journal(wal) if entry.get("status") == "COMPLETED"}
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    catalog_done = set()
    if output.exists():
        for line_number, line in enumerate(output.read_text(encoding="utf-8").splitlines(), 1):
            if line.strip():
                record = json.loads(line)
                if record.get("visibility") == "public" and record.get("private") is not True:
                    catalog_done.add(record.get("repository"))
    for namespace in namespaces:
        handle = namespace["handle"]
        endpoint = "orgs" if namespace.get("kind", "user") == "org" else "users"
        page = 1
        while True:
            url = f"{args.api}/{endpoint}/{handle}/repos?per_page=100&page={page}&type=public&sort=full_name&direction=asc"
            data, _headers = get_json(url, token, args.timeout)
            if not isinstance(data, list):
                raise ValueError("GitHub repository listing response was not an array")
            if not data:
                break
            for repo in sorted(data, key=lambda item: item.get("full_name", "")):
                # Privacy gate precedes every field read, traffic request, and disk write.
                if repo.get("private") is True or str(repo.get("visibility", "")).lower() != "public":
                    continue
                full_name = repo.get("full_name")
                if not isinstance(full_name, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", full_name):
                    continue
                if full_name in done:
                    continue
                if full_name in catalog_done:
                    append_journal(wal, {"repository": full_name, "status": "COMPLETED"})
                    done.add(full_name)
                    continue
                clone_count = None
                try:
                    traffic, _ = get_json(f"{args.api}/repos/{full_name}/traffic/clones", token, args.timeout)
                    clone_count = traffic.get("count") if isinstance(traffic, dict) else None
                except (HTTPError, URLError, TimeoutError):
                    clone_count = None
                topics = sorted(repo.get("topics") or [])
                planes = sorted({topic.split(":", 1)[1] for topic in topics
                                 if topic.startswith("mesh-plane:") and topic.split(":", 1)[1] in PLANES})
                record = {"namespace": handle, "repository": full_name, "name": repo.get("name"),
                          "description": repo.get("description"), "html_url": repo.get("html_url"),
                          "default_branch": repo.get("default_branch"), "visibility": "public", "private": False,
                          "archived": bool(repo.get("archived")), "created_at": repo.get("created_at"),
                          "updated_at": repo.get("updated_at"), "pushed_at": repo.get("pushed_at"),
                          "language": repo.get("language"), "topics": topics, "planes": planes,
                          "stargazers_count": repo.get("stargazers_count", 0), "forks_count": repo.get("forks_count", 0),
                          "clone_count_14d": clone_count}
                with output.open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n")
                    stream.flush()
                    os.fsync(stream.fileno())
                append_journal(wal, {"repository": full_name, "status": "COMPLETED"})
                done.add(full_name)
                catalog_done.add(full_name)
            if len(data) < 100:
                break
            page += 1
    print(json.dumps({"catalog": str(output), "completed_public_repositories": len(done)}, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, HTTPError, URLError, TimeoutError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2)
