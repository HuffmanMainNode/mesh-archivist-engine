#!/usr/bin/env python3
"""Deterministic node lifecycle CLI; Python standard library only."""
import argparse, hashlib, json, os, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path

ZERO = "0" * 64
PLANES = {"contract-plane", "ingress-plane", "compute-plane", "provenance-plane", "control-plane", "tooling-plane"}
def canonical(obj): return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
def digest(data): return hashlib.sha256(data).hexdigest()
def wal_path(root): return Path(root) / ".runtime" / "wal.jsonl"
def read_wal(root):
    path = wal_path(root)
    if not path.exists(): return []
    entries=[]; previous=ZERO
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        try: entry=json.loads(line)
        except json.JSONDecodeError as exc: raise ValueError(f"invalid WAL JSON at line {number}: {exc}") from exc
        claimed=entry.get("entry_hash")
        body={k:v for k,v in entry.items() if k != "entry_hash"}
        if body.get("sequence") != number: raise ValueError(f"WAL sequence mismatch at line {number}")
        if body.get("prev_hash") != previous: raise ValueError(f"WAL predecessor mismatch at line {number}")
        actual=digest(canonical(body).encode("utf-8"))
        if claimed != actual: raise ValueError(f"WAL digest mismatch at line {number}")
        if body.get("status") not in {"PENDING","COMMITTED","FAILED"}: raise ValueError(f"invalid WAL status at line {number}")
        entries.append(entry); previous=claimed
    return entries
def append_checkpoint(root, step, status, artifact=None, note=""):
    root=Path(root); path=wal_path(root); path.parent.mkdir(parents=True,exist_ok=True)
    entries=read_wal(root); previous=entries[-1]["entry_hash"] if entries else ZERO
    body={"sequence":len(entries)+1,"timestamp":datetime.now(timezone.utc).isoformat(),"step":step,"status":status,"artifact":artifact,"note":note,"prev_hash":previous}
    entry=dict(body); entry["entry_hash"]=digest(canonical(body).encode("utf-8"))
    with path.open("a",encoding="utf-8") as stream:
        stream.write(canonical(entry)+"\n"); stream.flush(); os.fsync(stream.fileno())
    return entry
def topological_sort(lock):
    satellites=lock.get("satellites",[]); graph={item["node_id"]:item.get("depends_on",[]) for item in satellites}
    if len(graph)!=len(satellites): raise ValueError("duplicate satellite node_id")
    state={}; ordered=[]
    def visit(node):
        if node not in graph: raise ValueError(f"missing dependency: {node}")
        if state.get(node)==1: raise ValueError(f"dependency cycle detected at {node}")
        if state.get(node)==2: return
        state[node]=1
        for dep in sorted(graph[node]): visit(dep)
        state[node]=2; ordered.append(node)
    for node in sorted(graph): visit(node)
    return ordered
def verify(root):
    root=Path(root); meta_path=root/".mesh-node.json"
    if not meta_path.is_file(): raise ValueError("missing .mesh-node.json")
    meta=json.loads(meta_path.read_text(encoding="utf-8"))
    required=("schema_version","node_id","namespace","visibility","tier","plane","parent")
    missing=[key for key in required if key not in meta]
    if missing: raise ValueError("missing node fields: "+", ".join(missing))
    if meta["visibility"] not in {"private","public"}: raise ValueError("invalid visibility")
    if not isinstance(meta["tier"],int) or not 1 <= meta["tier"] <= 4: raise ValueError("tier must be 1..4")
    if meta["plane"] not in PLANES: raise ValueError("invalid architectural plane")
    lock_path=root/"mesh.lock"; order=[]
    if lock_path.exists(): order=topological_sort(json.loads(lock_path.read_text(encoding="utf-8")))
    read_wal(root)
    return {"node_id":meta["node_id"],"tier":meta["tier"],"dependency_order":order,"wal_entries":len(read_wal(root))}
def do_init(args):
    root=Path(args.path); root.mkdir(parents=True,exist_ok=True); (root/".runtime").mkdir(exist_ok=True)
    meta={"schema_version":"1.0.0","node_id":args.node_id,"namespace":args.namespace,"visibility":args.visibility,"tier":args.tier,"plane":args.plane,"parent":args.parent or None}
    (root/".mesh-node.json").write_text(json.dumps(meta,indent=2)+"\n",encoding="utf-8")
    lock={"schema_version":"1.0.0","env_defaults":{},"bootstrap_commands":[],"healthcheck_command":[sys.executable,"-c","print('healthcheck: ok')"]}
    (root/"summon.lock").write_text(json.dumps(lock,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"initialized":str(root),"node_id":args.node_id},sort_keys=True)); return 0
def do_checkpoint(args):
    entry=append_checkpoint(args.path,args.step,args.status,args.artifact,args.note)
    print(json.dumps({"sequence":entry["sequence"],"entry_hash":entry["entry_hash"]},sort_keys=True)); return 0
def do_resume(args):
    entries=read_wal(args.path); committed=[e for e in entries if e["status"]=="COMMITTED"]
    resolved={e["step"] for e in entries if e["status"]=="COMMITTED"}
    pending={e["step"] for e in entries if e["status"]=="PENDING" and e["step"] not in resolved}
    failed={e["step"] for e in entries if e["status"]=="FAILED" and e["step"] not in resolved}
    result={"entries":len(entries),"last_committed":committed[-1]["step"] if committed else None,"pending_replay":sorted(pending),"failed_steps":sorted(failed)}
    print(json.dumps(result,sort_keys=True)); return 0
def do_summon(args):
    root=Path(args.path); lock=json.loads((root/"summon.lock").read_text(encoding="utf-8"))
    env=os.environ.copy()
    for key,value in lock.get("env_defaults",{}).items(): env.setdefault(str(key),str(value))
    for command in lock.get("bootstrap_commands",[]):
        if not isinstance(command,list) or not command: raise ValueError("bootstrap command must be a non-empty argv array")
        subprocess.run(command,cwd=root,env=env,check=True)
    health=lock.get("healthcheck_command")
    if not isinstance(health,list) or not health: raise ValueError("healthcheck_command is required")
    subprocess.run(health,cwd=root,env=env,check=True)
    print(json.dumps({"summoned":str(root),"healthcheck":"passed"},sort_keys=True)); return 0
def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__); sub=parser.add_subparsers(dest="command",required=True)
    p=sub.add_parser("init"); p.add_argument("path"); p.add_argument("--node-id",required=True); p.add_argument("--namespace",required=True); p.add_argument("--visibility",choices=["private","public"],required=True); p.add_argument("--tier",type=int,choices=range(1,5),required=True); p.add_argument("--plane",choices=sorted(PLANES),required=True); p.add_argument("--parent",default=""); p.set_defaults(func=do_init)
    p=sub.add_parser("checkpoint"); p.add_argument("path"); p.add_argument("--step",required=True); p.add_argument("--status",choices=["PENDING","COMMITTED","FAILED"],required=True); p.add_argument("--artifact"); p.add_argument("--note",default=""); p.set_defaults(func=do_checkpoint)
    p=sub.add_parser("resume"); p.add_argument("path"); p.set_defaults(func=do_resume)
    p=sub.add_parser("summon"); p.add_argument("path"); p.set_defaults(func=do_summon)
    p=sub.add_parser("verify"); p.add_argument("path"); p.set_defaults(func=lambda a: (print(json.dumps(verify(a.path),sort_keys=True)) or 0))
    args=parser.parse_args(argv)
    try: return args.func(args)
    except (OSError,ValueError,KeyError,json.JSONDecodeError,subprocess.CalledProcessError) as exc:
        print(f"error: {exc}",file=sys.stderr); return 2
if __name__=="__main__": raise SystemExit(main())
