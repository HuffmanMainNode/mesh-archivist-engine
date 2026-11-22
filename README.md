# Mesh Archivist Engine

Version: 1.0.1 development line  
Runtime: Python 3.11+ standard library; POSIX file locking for journal safety

## Scope

`meshctl.py` initializes, checkpoints, resumes, summons, and verifies individual mesh nodes. `crawl_namespaces.py` performs an explicitly invoked public-only GitHub inventory scan. `gap_planner.py` identifies plane coverage gaps. `diode_promote.py` creates a deny-by-default public projection from a reviewed catalog.

This is local repository tooling, not a hosted service or an always-running account scanner. Namespace configuration ships with placeholders and performs no network access until an operator replaces them.

## Requirements

Python 3.11 or newer. No third-party Python packages. Journal concurrency uses POSIX `flock`. GitHub API access uses `urllib.request` and an optional caller-supplied `GITHUB_TOKEN`. Never place tokens in TOML, command history, task envelopes, or catalogs.

## CLI

```sh
python3 meshctl.py init ./node --node-id example --namespace example --visibility private --tier 1 --plane tooling-plane
python3 meshctl.py checkpoint ./node --step bootstrap --status PENDING
python3 meshctl.py resume ./node
python3 meshctl.py verify ./node
python3 meshctl.py summon ./node                 # dry-run only
python3 meshctl.py summon ./node --execute       # explicit execution after reviewing summon.lock
```

Summon is dry-run by default. Execution uses argv arrays without a shell, applies a timeout to each command, and records pending/committed/failed lifecycle entries in the WAL. Review every command before using `--execute`.

## WAL and recovery

The JSONL journal is SHA-256 hash-chained, serialized under an advisory file lock, appended with one write, flushed, and fsynced. A malformed unterminated final fragment is treated as an interrupted append and truncated to the last complete record. A malformed complete line, sequence gap, predecessor mismatch, or digest mismatch is rejected. A complete final JSON object without a newline is retained and normalized with a delimiter.

`resume` validates the journal and reports unresolved work. It is deliberately plan-only: arbitrary commands are never replayed automatically. An operator or higher-level orchestrator must inspect the pending operation and decide whether retry is safe.

## Dependency contract

The root `.mesh-node.json` declares `repo-mesh-blueprint`; `mesh.lock` pins its URI, release identifier, and commit SHA. `verify` rejects unsupported major versions, mismatched declarations, missing graph nodes, duplicate IDs, and dependency cycles. A commit pin is an identity declaration; consumers must independently retrieve and verify that commit before trusting remote content.

## Public namespace inventory

```sh
python3 crawl_namespaces.py --config namespaces.toml --output ARCHIVAL_CATALOG.jsonl
python3 gap_planner.py --catalog ARCHIVAL_CATALOG.jsonl --output next_repo_proposals.json
python3 diode_promote.py --input ARCHIVAL_CATALOG.jsonl --output PUBLIC_SHOWCASE_LEDGER.jsonl --root-output PUBLIC_LEDGER_MERKLE.txt --approve-review
```

The crawler accepts only explicitly configured public user/organization namespaces. It discards private or non-public repository entries before reading repository metadata, requesting traffic, or writing catalog records. A catalog write that completes before a WAL append is reconciled on the next run. GitHub traffic data is optional and depends on the token's permissions and GitHub's availability window.

The diode exports only a fixed allowlist, requires public visibility, excludes private records, and requires an explicit human review confirmation. Its Merkle root proves deterministic integrity of the exported record set; it does not provide confidentiality, authenticity, or authorization.

## Agent integration

See `AGENT_HANDSHAKE.md`. The adapter rejects scope escapes and requires a host-provided cryptographic approval verifier for every side-effecting operation (`checkpoint`, `summon`, `crawl`, `promote`, and `mutate`). The adapter does not implement a signature scheme or execute operations itself.

## Verification

```sh
make verify
make test
make clean
```

## License

Apache-2.0.
