# Security Policy

## Supported versions

Security fixes are applied to the current default branch. Published release tags are immutable historical snapshots and are not silently rewritten.

## Reporting a vulnerability

Do not publish exploit details, credentials, private repository names, or sensitive logs in a public issue. Use GitHub's private vulnerability reporting feature for this repository when available. If private reporting is unavailable, contact the repository owner through a verified private channel and include a concise impact description and reproduction steps.

## Security boundaries

- The crawler is intended to inventory public repositories only. It must reject private or non-public repository records before reading their metadata or requesting traffic.
- Never place GitHub tokens, private keys, or credentials in namespace configuration, issue reports, catalogs, or task envelopes.
- The agent adapter requires a host-supplied cryptographic approval verifier for every side-effecting operation.
- The public projection is an export filter, not a substitute for separate credentials, storage, and human review.
- WAL hashes provide tamper evidence, not identity authentication or protection against a privileged attacker.

## Response

Reports will be triaged, reproduced where possible, and addressed through a reviewed patch and a new release. Do not assume a report is accepted until acknowledged.
