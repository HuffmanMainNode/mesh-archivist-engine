#!/usr/bin/env python3
"""Produce deterministic repository proposals for uncovered mesh planes."""
import argparse,json
from pathlib import Path
PLANES=("contract-plane","ingress-plane","compute-plane","provenance-plane","control-plane","tooling-plane")
def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--catalog",required=True); ap.add_argument("--output",default="next_repo_proposals.json"); args=ap.parse_args()
    records=[json.loads(x) for x in Path(args.catalog).read_text(encoding="utf-8").splitlines() if x.strip()]
    grouped={}
    for r in records:
        ns=r.get("namespace","unassigned"); grouped.setdefault(ns,{p:[] for p in PLANES})
        planes=r.get("planes",[])
        primary=r.get("plane")
        if primary in PLANES: planes=list(planes)+[primary]
        for plane in set(planes):
            if plane in PLANES: grouped[ns][plane].append(r.get("repository","unknown"))
    proposals=[]
    for ns,coverage in sorted(grouped.items()):
        for plane,repos in coverage.items():
            if not repos: proposals.append({"namespace":ns,"plane":plane,"proposed_repository":ns.lower().replace("_","-")+"-"+plane.replace("-plane","")+"-node","rationale":"No catalogued repository declares coverage for this architectural plane.","status":"proposal-only"})
    result={"schema_version":"1.0.0","planes":list(PLANES),"namespace_count":len(grouped),"next_repo_proposals":proposals}
    Path(args.output).write_text(json.dumps(result,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps({"output":args.output,"proposal_count":len(proposals)},sort_keys=True))
if __name__=="__main__": main()
