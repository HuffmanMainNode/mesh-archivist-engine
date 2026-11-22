# Contributing

## Scope

Contributions should preserve the standard-library-only runtime, deterministic output, explicit namespace boundaries, and fail-closed security posture.

## Before opening a pull request

1. Explain the problem and the intended behavioral change.
2. Add tests for normal behavior, invalid input, and failure/recovery paths.
3. Run `make verify` and `make test`.
4. Do not include real namespace handles, access tokens, private repository metadata, local paths, or personal data in fixtures.
5. Keep changes scoped. Avoid unrelated formatting or generated artifacts.

## Design requirements

- Network access must remain explicit and caller-controlled.
- Public crawling must reject private repositories before metadata collection.
- Side-effecting agent operations require host-authenticated approval.
- WAL records must be hash-verified and append-safe.
- Public promotion must remain allowlisted and require an explicit review confirmation.

## Pull requests

Describe compatibility impact, security implications, test evidence, and any limitations that remain. Never claim a test or workflow passed unless its result is available.
