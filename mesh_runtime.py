"""Durable, hash-chained JSONL journal primitives for POSIX runtimes."""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
from contextlib import contextmanager
from pathlib import Path

ZERO_HASH = "0" * 64


def canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@contextmanager
def journal_lock(path: Path):
    lock_path = path.with_name(path.name + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def read_journal(path: Path, *, repair_incomplete_tail: bool = True) -> list[dict]:
    path = Path(path)
    if not path.exists():
        return []
    with journal_lock(path):
        raw = path.read_bytes()
        if raw and not raw.endswith(b"\n"):
            boundary = raw.rfind(b"\n") + 1
            tail = raw[boundary:]
            if not repair_incomplete_tail:
                raise ValueError("journal has an unterminated final record")
            # A complete JSON object without its delimiter is accepted only if it
            # parses and verifies. Otherwise truncate only this uncommitted tail.
            try:
                candidate = json.loads(tail.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                with path.open("r+b") as stream:
                    stream.truncate(boundary)
                    stream.flush()
                    os.fsync(stream.fileno())
                raw = raw[:boundary]
            else:
                if not isinstance(candidate, dict):
                    raise ValueError("journal final record is not an object")
                raw += b"\n"
                with path.open("ab") as stream:
                    stream.write(b"\n")
                    stream.flush()
                    os.fsync(stream.fileno())
        entries: list[dict] = []
        previous = ZERO_HASH
        for sequence, line in enumerate(raw.splitlines(), 1):
            if not line:
                raise ValueError(f"empty journal record at line {sequence}")
            try:
                entry = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid journal JSON at line {sequence}: {exc}") from exc
            if not isinstance(entry, dict):
                raise ValueError(f"journal record {sequence} is not an object")
            claimed = entry.get("entry_hash")
            body = {key: value for key, value in entry.items() if key != "entry_hash"}
            if body.get("sequence") != sequence:
                raise ValueError(f"journal sequence mismatch at line {sequence}")
            if body.get("prev_hash") != previous:
                raise ValueError(f"journal predecessor mismatch at line {sequence}")
            actual = sha256(canonical(body).encode("utf-8"))
            if claimed != actual:
                raise ValueError(f"journal digest mismatch at line {sequence}")
            entries.append(entry)
            previous = claimed
        return entries


def append_journal(path: Path, body: dict) -> dict:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with journal_lock(path):
        entries = read_journal_unlocked(path)
        record = dict(body)
        record["sequence"] = len(entries) + 1
        record["prev_hash"] = entries[-1]["entry_hash"] if entries else ZERO_HASH
        record["entry_hash"] = sha256(canonical(record).encode("utf-8"))
        payload = (canonical(record) + "\n").encode("utf-8")
        descriptor = os.open(path, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
        try:
            written = os.write(descriptor, payload)
            if written != len(payload):
                raise OSError("short journal append; tail will be repaired on next read")
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        return record


def read_journal_unlocked(path: Path) -> list[dict]:
    if not path.exists():
        return []
    raw = path.read_bytes()
    if raw and not raw.endswith(b"\n"):
        boundary = raw.rfind(b"\n") + 1
        tail = raw[boundary:]
        try:
            json.loads(tail.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            with path.open("r+b") as stream:
                stream.truncate(boundary)
                stream.flush()
                os.fsync(stream.fileno())
            raw = raw[:boundary]
        else:
            raw += b"\n"
            with path.open("ab") as stream:
                stream.write(b"\n")
                stream.flush()
                os.fsync(stream.fileno())
    entries = []
    previous = ZERO_HASH
    for sequence, line in enumerate(raw.splitlines(), 1):
        if not line:
            raise ValueError(f"empty journal record at line {sequence}")
        entry = json.loads(line)
        claimed = entry.get("entry_hash")
        body = {key: value for key, value in entry.items() if key != "entry_hash"}
        if body.get("sequence") != sequence or body.get("prev_hash") != previous:
            raise ValueError(f"journal sequence or predecessor mismatch at line {sequence}")
        if claimed != sha256(canonical(body).encode("utf-8")):
            raise ValueError(f"journal digest mismatch at line {sequence}")
        entries.append(entry)
        previous = claimed
    return entries
