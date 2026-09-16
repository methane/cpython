"""Three additional process blocks for four noisy/material cohort differences."""
import hashlib,json,os,signal,subprocess,time,statistics
from pathlib import Path
O=Path(__file__).resolve().parent
s=json.loads((O/'cohort-state.json').read_text())
records=[]
for name in ['chaos','raytrace','regex_dna','networkx_connected_components']:
 for block,order in enumerate([['main','before','candidate'],['before','candidate','main'],['candidate','main','before']]):
  for v in order:
   original=next(r for r in s['records'] if r['name']==name and r['tag']=='0' and r['variant']==v)
   cmd=original['command'].copy();target=O/f'extra-{name}-{block}-{v}.json';cmd[-3]=str(target) if cmd[-4]=='-o' else cmd[-3]
   # Replace the actual output argument, retaining every timing option.
   cmd[cmd.index('-o')+1]=str(target)
   env={**os.environ,'PYTHON_JIT':'1','PYTHONPATH':str(O.parents[1]/'jit-artifacts/pyperformance-20260915/venv-main/lib/python3.16/site-packages'),'PYTHONPYCACHEPREFIX':f'/tmp/method-cohort-{v}'}
   assert hashlib.sha256(Path(cmd[0]).read_bytes()).hexdigest()==s['sha256'][v]
   start=time.monotonic()
   with target.with_suffix('.log').open('w') as log:
    p=subprocess.Popen(cmd,env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
    try:rc=p.wait(timeout=original['timeout'])
    except subprocess.TimeoutExpired:os.killpg(p.pid,signal.SIGKILL);p.wait();rc=124
   r={'name':name,'variant':v,'block':block,'rc':rc,'wall':time.monotonic()-start,'command':cmd}
   if not rc:
    d=json.loads(target.read_text());values=[x for b in d['benchmarks'] for run in b['runs'] for x in run.get('values',[])];r['mean']=statistics.mean(values)
   records.append(r);(O/'supplementary.json').write_text(json.dumps(records,indent=2)+'\n');print(r['name'],block,v,rc,r.get('mean'),flush=True)
