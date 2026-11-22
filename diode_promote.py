#!/usr/bin/env python3
"""Deny-by-default public catalog projection and deterministic Merkle root."""
import argparse,hashlib,json,os,sys
from pathlib import Path
ALLOW={"namespace","repository","name","description","html_url","default_branch","visibility","archived","created_at","updated_at","pushed_at","language","topics","planes","stargazers_count","forks_count","clone_count_14d"}
def canonical(x): return json.dumps(x,sort_keys=True,separators=(",",":"),ensure_ascii=False)
def sha(b): return hashlib.sha256(b).hexdigest()
def merkle(leaves):
    if not leaves: return sha(b"")
    level=[sha(x) for x in leaves]
    while len(level)>1:
        if len(level)%2: level.append(level[-1])
        level=[sha(bytes.fromhex(level[i])+bytes.fromhex(level[i+1])) for i in range(0,len(level),2)]
    return level[0]
def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--input",required=True); ap.add_argument("--output",required=True); ap.add_argument("--root-output",default="PUBLIC_LEDGER_MERKLE.txt"); args=ap.parse_args()
    source=Path(args.input); records=[]; redacted=0
    for line in source.read_text(encoding="utf-8").splitlines():
        if not line.strip(): continue
        item=json.loads(line)
        if item.get("private") is True or str(item.get("visibility", "")).lower()=="private": redacted+=1; continue
        public={k:item[k] for k in sorted(ALLOW) if k in item}
        if not public: redacted+=1; continue
        records.append(public)
    records.sort(key=lambda r:(str(r.get("namespace","")),str(r.get("repository",""))))
    leaves=[canonical(r).encode("utf-8") for r in records]
    out=Path(args.output); out.parent.mkdir(parents=True,exist_ok=True)
    with out.open("w",encoding="utf-8") as f:
        for record in records: f.write(canonical(record)+"\n")
        f.flush(); os.fsync(f.fileno())
    root=merkle(leaves)
    Path(args.root_output).write_text(f"algorithm=sha256-merkle-v1\nroot={root}\nrecords={len(records)}\nredacted={redacted}\n",encoding="utf-8")
    print(json.dumps({"public_records":len(records),"redacted_records":redacted,"merkle_root":root},sort_keys=True))
if __name__=="__main__":
    try: main()
    except (OSError,ValueError,json.JSONDecodeError) as exc: print(f"error: {exc}",file=sys.stderr); raise SystemExit(2)
