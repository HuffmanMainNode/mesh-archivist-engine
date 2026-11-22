import hashlib,json,os,subprocess,sys,tempfile,unittest
from pathlib import Path
ENGINE=Path(__file__).resolve().parents[1]
MESH=ENGINE/"meshctl.py"
def run(*args): return subprocess.run([sys.executable,*map(str,args)],capture_output=True,text=True)
def canonical(x): return json.dumps(x,sort_keys=True,separators=(",",":"),ensure_ascii=False)
def root_for(lines):
    leaves=[hashlib.sha256(x).hexdigest() for x in lines]
    if not leaves: return hashlib.sha256(b"").hexdigest()
    while len(leaves)>1:
        if len(leaves)%2: leaves.append(leaves[-1])
        leaves=[hashlib.sha256(bytes.fromhex(leaves[i])+bytes.fromhex(leaves[i+1])).hexdigest() for i in range(0,len(leaves),2)]
    return leaves[0]
class EngineE2E(unittest.TestCase):
    def setUp(self): self.tmp=Path(tempfile.mkdtemp())
    def test_agent_package_validates_scope_and_emits_result_digest(self):
        sys.path.insert(0,str(ENGINE))
        from mesh_agent import PROTOCOL, build_result, capability_manifest, validate_task
        from datetime import datetime, timezone, timedelta
        task={"protocol":PROTOCOL,"task_id":"task-1","origin_namespace":"ns","target_node":"node-a","requested_plane":"contract-plane","operation":"verify","scope":["schemas/"],"inputs_sha256":"a"*64,"expected_contract":"1.0.0","expires_at":(datetime.now(timezone.utc)+timedelta(minutes=5)).isoformat(),"approval_ref":None}
        checked=validate_task(task,{"node-a"}); self.assertEqual(checked["task_id"],"task-1")
        result=build_result(checked,"node-a","completed",{"verified":True}); self.assertEqual(len(result["result_sha256"]),64)
        self.assertTrue(capability_manifest()["read_only_by_default"])
        task["scope"]=["../../outside"]
        with self.assertRaises(ValueError): validate_task(task,{"node-a"})
        task["scope"]=["schemas/"]; task["operation"]="mutate"
        with self.assertRaises(ValueError): validate_task(task,{"node-a"})
    def test_wal_chain_and_crash_recovery(self):
        node=self.tmp/"node"
        self.assertEqual(run(MESH,"init",node,"--node-id","n1","--namespace","ns","--visibility","private","--tier","1","--plane","tooling-plane").returncode,0)
        self.assertEqual(run(MESH,"checkpoint",node,"--step","compile","--status","PENDING").returncode,0)
        resume=run(MESH,"resume",node); self.assertEqual(resume.returncode,0); self.assertIn('"pending_replay": ["compile"]',resume.stdout)
        self.assertEqual(run(MESH,"checkpoint",node,"--step","compile","--status","COMMITTED").returncode,0)
        resume=run(MESH,"resume",node); self.assertIn('"last_committed": "compile"',resume.stdout); self.assertIn('"pending_replay": []',resume.stdout)
        wal=(node/".runtime/wal.jsonl").read_text().splitlines(); prev="0"*64
        for i,line in enumerate(wal,1):
            e=json.loads(line); h=e.pop("entry_hash"); self.assertEqual(e["prev_hash"],prev); self.assertEqual(hashlib.sha256(canonical(e).encode()).hexdigest(),h); prev=h
    def test_dag_sort_and_cycle_detection(self):
        node=self.tmp/"dag"; run(MESH,"init",node,"--node-id","root","--namespace","ns","--visibility","public","--tier","2","--plane","compute-plane")
        meta=json.loads((node/".mesh-node.json").read_text()); meta["depends_on"]=["a","b","c"]; (node/".mesh-node.json").write_text(json.dumps(meta))
        lock={"schema_version":"1.0.0","satellites":[{"node_id":"c","depends_on":["b"],"uri":"x","version":"1"},{"node_id":"b","depends_on":["a"],"uri":"x","version":"1"},{"node_id":"a","depends_on":[],"uri":"x","version":"1"}]}
        (node/"mesh.lock").write_text(json.dumps(lock)); result=run(MESH,"verify",node); self.assertEqual(result.returncode,0,result.stderr); self.assertLess(result.stdout.index('"a"'),result.stdout.index('"b"'))
        lock["satellites"][0]["depends_on"]=["b"]; lock["satellites"][1]["depends_on"]=["c"]; (node/"mesh.lock").write_text(json.dumps(lock))
        result=run(MESH,"verify",node); self.assertNotEqual(result.returncode,0); self.assertIn("cycle",result.stderr)
        lock["satellites"][0]["depends_on"]=["absent-node"]; lock["satellites"][1]["depends_on"]=["a"]; (node/"mesh.lock").write_text(json.dumps(lock))
        result=run(MESH,"verify",node); self.assertNotEqual(result.returncode,0); self.assertIn("missing dependency",result.stderr)
    def test_summon_bootstrap_and_healthcheck(self):
        node=self.tmp/"summon"; run(MESH,"init",node,"--node-id","n","--namespace","ns","--visibility","private","--tier","1","--plane","tooling-plane")
        marker=node/"bootstrapped.txt"; lock={"schema_version":"1.0.0","env_defaults":{"MESH_TEST_DEFAULT":"set"},"bootstrap_commands":[[sys.executable,"-c",f"from pathlib import Path; Path({str(marker)!r}).write_text('ok')"]],"healthcheck_command":[sys.executable,"-c","import os; assert os.environ['MESH_TEST_DEFAULT']=='set'"]}
        (node/"summon.lock").write_text(json.dumps(lock)); result=run(MESH,"summon",node,"--execute"); self.assertEqual(result.returncode,0,result.stderr); self.assertEqual(marker.read_text(),"ok")
    def test_crawler_refuses_placeholder_namespaces_without_network(self):
        catalog=self.tmp/"catalog.jsonl"; wal=self.tmp/"crawler-wal.jsonl"
        result=run(ENGINE/"crawl_namespaces.py","--config",ENGINE/"namespaces.toml","--output",catalog,"--wal",wal)
        self.assertNotEqual(result.returncode,0)
        self.assertIn("placeholder handles remain",result.stderr)
        self.assertFalse(catalog.exists())
    def test_gap_planner_uses_explicit_plane_tags(self):
        catalog=self.tmp/"catalog.jsonl"; output=self.tmp/"proposals.json"
        planes=["contract-plane","ingress-plane","compute-plane","provenance-plane","control-plane","tooling-plane"]
        rows=[{"namespace":"ns-a","repository":"ns-a/contracts","planes":["contract-plane"]},{"namespace":"ns-b","repository":"ns-b/all-planes","planes":planes}]
        catalog.write_text("".join(canonical(row)+"\n" for row in rows))
        result=run(ENGINE/"gap_planner.py","--catalog",catalog,"--output",output); self.assertEqual(result.returncode,0,result.stderr)
        report=json.loads(output.read_text()); proposals=report["next_repo_proposals"]
        self.assertEqual(len([p for p in proposals if p["namespace"]=="ns-a"]),5)
        self.assertEqual(len([p for p in proposals if p["namespace"]=="ns-b"]),0)
    def test_diode_redaction_allowlist_and_merkle(self):
        source=self.tmp/"private.jsonl"; out=self.tmp/"public.jsonl"; root=self.tmp/"root.txt"
        rows=[{"namespace":"ns","repository":"public/repo","visibility":"public","private":False,"description":"public","secret":"must-not-leak"},{"namespace":"ns","repository":"private/repo","private":True,"description":"private"},{"namespace":"ns","repository":"private-by-visibility/repo","visibility":"private","description":"also private"}]
        source.write_text("".join(canonical(r)+"\n" for r in rows))
        result=run(ENGINE/"diode_promote.py","--input",source,"--output",out,"--root-output",root,"--approve-review"); self.assertEqual(result.returncode,0,result.stderr)
        emitted=out.read_text(); self.assertIn("public/repo",emitted); self.assertNotIn("private/repo",emitted); self.assertNotIn("must-not-leak",emitted)
        public=[json.loads(x) for x in emitted.splitlines()]; expected=root_for([canonical(x).encode() for x in public]); self.assertIn("root="+expected,root.read_text()); self.assertIn("redacted=2",root.read_text())
if __name__=="__main__": unittest.main(verbosity=2)
