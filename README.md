# Mesh Archivist Engine

Version: 1.0.0  
Runtime: Python 3.11+ standard library and POSIX shell for Make targets

## Scope

`meshctl.py` initializes, checkpoints, resumes, summons, and verifies individual mesh nodes. `crawl_namespaces.py` performs an explicitly invoked GitHub inventory scan. `gap_planner.py` identifies plane coverage gaps. `diode_promote.py` creates a deny-by-default public projection from a private catalog.

The engine does not run as a hosted service and does not scan accounts automatically. The namespace file ships with generic placeholders. Replace them only after reviewing scope and credentials.

## Requirements

Python 3.11 or newer. No third-party Python packages. GitHub API access uses `urllib.request` and a user-supplied token from `GITHUB_TOKEN`; never place tokens in TOML, command history, or catalogs.

## CLI

```sh
python3 meshctl.py init ./node --node-id example --namespace example --visibility private --tier 1 --plane tooling-plane --parent ''
python3 meshctl.py checkpoint ./node --step bootstrap --status PENDING
python3 meshctl.py resume ./node
python3 meshctl.py verify ./node
python3 meshctl.py summon ./node
```

`checkpoint` supports `PENDING`, `COMMITTED`, and `FAILED`. Each entry is canonical JSON, SHA-256 chained, appended with flush and `fsync`. `resume` validates the entire log before reporting the last committed checkpoint and unresolved pending steps.

`summon` executes the commands in `summon.lock`. Review the file before running it. Existing environment variables take precedence over `env_defaults`.

## Namespace inventory

```sh
python3 crawl_namespaces.py --config namespaces.toml --output ARCHIVAL_CATALOG.jsonl
python3 gap_planner.py --catalog ARCHIVAL_CATALOG.jsonl --output next_repo_proposals.json
python3 diode_promote.py --input ARCHIVAL_CATALOG.jsonl --output PUBLIC_SHOWCASE_LEDGER.jsonl --root-output PUBLIC_LEDGER_MERKLE.txt
```

The crawler is opt-in and reads only the namespace handles explicitly listed in TOML. It records completed repositories in `.crawler-wal.jsonl`, reconciles a catalog write interrupted before its WAL completion record, and collects repository metadata plus clone traffic where the token has access. GitHub clone traffic is subject to GitHub's availability window and permission model. Declare plane coverage with exact GitHub topics such as `mesh-plane:contract-plane`; the planner does not guess architectural coverage from repository prose.

## Dual projection

Keep the Private Workshop Inventory in a protected location. The diode emits only a fixed public field allowlist, excludes records with `private: true`, and reports the redacted count. Review the output before publishing. Merkle integrity is not an access-control mechanism.

## Verification

```sh
make verify
make test
make clean
```

`make clean` removes only local Python bytecode caches and test scratch files under `tests/.tmp`; it does not delete catalogs, WALs, node state, or source files.

## Agent integration

See `AGENT_HANDSHAKE.md`. Agent-facing consumers should validate task envelopes, declare capabilities, preserve scope ceilings, emit deterministic JSON, and return evidence references. The CLI is intentionally importable by standard-library-only adapters. The `mesh_agent` package supplies envelope validation, capability declarations, and deterministic result envelopes for agent runtimes.

## License

Apache-2.0.
