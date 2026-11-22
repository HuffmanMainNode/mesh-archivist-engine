#!/usr/bin/env python3
"""Opt-in GitHub namespace inventory crawler; standard library only."""
import argparse, hashlib, json, os, sys, tomllib
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
ZERO="0"*64
PLANES={"contract-plane","ingress-plane","compute-plane","provenance-plane","control-plane","tooling-plane"}
def canon(x): return json.dumps(x,sort_keys=True,separators=(",",":"),ensure_ascii=False)
def sha(x): return hashlib.sha256(x).hexdigest()
def wal_read(path):
    if not path.exists(): return []
    out=[]; prev=ZERO
    for i,line in enumerate(path.read_text().splitlines(),1):
        e=json.loads(line); h=e.pop("entry_hash")
        if e.get("sequence")!=i or e.get("prev_hash")!=prev or sha(canon(e).encode())!=h: raise ValueError(f"crawler WAL integrity failure at line {i}")
        e["entry_hash"]=h; out.append(e); prev=h
    return out
def wal_append(path,repo):
    entries=wal_read(path); body={"sequence":len(entries)+1,"repository":repo,"status":"COMPLETED","prev_hash":entries[-1]["entry_hash"] if entries else ZERO}
    e=dict(body); e["entry_hash"]=sha(canon(body).encode())
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("a") as f: f.write(canon(e)+"\n"); f.flush(); os.fsync(f.fileno())
def get_json(url,token):
    headers={"Accept":"application/vnd.github+json","X-GitHub-Api-Version":"2022-11-28","User-Agent":"mesh-archivist-engine/1.0"}
    if token: headers["Authorization"]="Bearer "+token
    req=Request(url,headers=headers)
    with urlopen(req,timeout=30) as response: return json.loads(response.read().decode("utf-8"))
def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--config",default="namespaces.toml"); ap.add_argument("--output",default="ARCHIVAL_CATALOG.jsonl"); ap.add_argument("--wal",default=".crawler-wal.jsonl"); ap.add_argument("--api",default="https://api.github.com"); args=ap.parse_args()
    cfg=tomllib.loads(Path(args.config).read_text(encoding="utf-8")); namespaces=cfg.get("namespaces",[])
    if not namespaces: raise SystemExit("no namespaces configured")
    if any(n.get("handle") in {"primary-core-account","standards-spec-account"} for n in namespaces): raise SystemExit("placeholder handles remain; configure real handles manually before crawling")
    token=os.environ.get("GITHUB_TOKEN"); wal=Path(args.wal); done={e["repository"] for e in wal_read(wal) if e.get("status")=="COMPLETED"}; output=Path(args.output); output.parent.mkdir(parents=True,exist_ok=True)
    catalog_done=set()
    if output.exists():
        for line in output.read_text(encoding="utf-8").splitlines():
            if line.strip(): catalog_done.add(json.loads(line).get("repository"))
    for ns in namespaces:
        handle=ns["handle"]; kind=ns.get("kind","user"); page=1
        while True:
            endpoint="orgs" if kind=="org" else "users"
            data=get_json(f"{args.api}/{endpoint}/{handle}/repos?per_page=100&page={page}&type=owner&sort=full_name&direction=asc",token)
            if not data: break
            for repo in sorted(data,key=lambda item:item.get("full_name","")):
                full=repo["full_name"]
                if full in done: continue
                if full in catalog_done:
                    wal_append(wal,full); done.add(full); continue
                clone_count=None
                try: clone_count=get_json(f"{args.api}/repos/{full}/traffic/clones",token).get("count")
                except (HTTPError,URLError): clone_count=None
                topics=sorted(repo.get("topics") or [])
                planes=sorted({topic.split(":",1)[1] for topic in topics if topic.startswith("mesh-plane:") and topic.split(":",1)[1] in PLANES})
                record={"namespace":handle,"repository":full,"name":repo.get("name"),"description":repo.get("description"),"html_url":repo.get("html_url"),"default_branch":repo.get("default_branch"),"visibility":repo.get("visibility"),"private":bool(repo.get("private")),"archived":bool(repo.get("archived")),"created_at":repo.get("created_at"),"updated_at":repo.get("updated_at"),"pushed_at":repo.get("pushed_at"),"language":repo.get("language"),"topics":topics,"planes":planes,"stargazers_count":repo.get("stargazers_count",0),"forks_count":repo.get("forks_count",0),"clone_count_14d":clone_count}
                with output.open("a",encoding="utf-8") as stream: stream.write(canon(record)+"\n"); stream.flush(); os.fsync(stream.fileno())
                wal_append(wal,full); done.add(full)
            if len(data)<100: break
            page+=1
    print(json.dumps({"catalog":str(output),"completed_repositories":len(done)},sort_keys=True))
if __name__=="__main__":
    try: main()
    except (OSError,ValueError,KeyError,HTTPError,URLError) as exc: print(f"error: {exc}",file=sys.stderr); raise SystemExit(2)
