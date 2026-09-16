"""Fixed 24-workload pyperformance screen; raw pyperf output is retained."""
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import statistics
import subprocess
import time

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
SITE = ROOT / 'jit-artifacts/pyperformance-20260915/venv-main/lib/python3.16/site-packages'
DATA = SITE / 'pyperformance/data-files/benchmarks'
NAMES = '''chaos comprehensions crypto_pyaes deltablue docutils fannkuch float go hexiom html5lib json_dumps json_loads meteor_contest nbody nqueens pidigits raytrace regex_dna richards richards_super spectral_norm telco tomli_loads networkx_connected_components'''.split()
BINARIES = {'main':OUT/'main-build/python', 'before':ROOT/'build-method-jit/python-before-matched', 'candidate':ROOT/'build-method-jit/python-final'}
HASHES = {k:hashlib.sha256(p.read_bytes()).hexdigest() for k,p in BINARIES.items()}
# Record all common site-packages sources and native dependencies (not pyc).
DEPENDENCIES = {str(p.relative_to(SITE)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(SITE.rglob('*')) if p.is_file() and p.suffix in ('.py','.so','.toml','.txt')}
state = {'binaries':{k:str(v) for k,v in BINARIES.items()},'sha256':HASHES,'dependencies':DEPENDENCIES,'cpu':2,'names':NAMES,'orders':[['main','before','candidate'],['candidate','before','main']], 'records':[]}
assert not (OUT/'cohort-state.json').exists()
(OUT/'cohort-state.json').write_text(json.dumps(state,indent=2)+'\n')

def read_result(path):
    data=json.loads(path.read_text()); values=[]; loops=None; names=[]
    for bench in data['benchmarks']:
        meta=data.get('metadata',{}) | bench.get('metadata',{})
        names.append(meta['name'])
        for run in bench['runs']:
            if run.get('values'):
                values.extend(run['values']); loops=(meta | run.get('metadata',{}))['loops']
    assert len(names)==1, names
    return statistics.mean(values), loops

def run(name, variant, tag, loops=None):
    network=name.startswith('networkx')
    script=DATA/('bm_networkx' if network else 'bm_'+name)/'run_benchmark.py'
    extra=['connected_components'] if network else []
    target=OUT/f'cohort-{name}-{tag}-{variant}.json'
    cmd=[str(BINARIES[variant]),str(script),*extra,'--affinity','2','-p','1','-n','5','-w','3','--min-time','0.05','--inherit-environ=PYTHON_JIT,PYTHONPATH,PYTHONPYCACHEPREFIX','-o',str(target)]
    if loops is not None: cmd += ['-l',str(loops)]
    env={**os.environ,'PYTHON_JIT':'1','PYTHONPATH':str(SITE),'PYTHONPYCACHEPREFIX':f'/tmp/method-cohort-{variant}'}
    start=time.monotonic(); timeout=15 if network else 45
    with target.with_suffix('.log').open('w') as log:
        p=subprocess.Popen(cmd,env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        try: rc=p.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(p.pid,signal.SIGKILL); p.wait(); rc=124
    record={'name':name,'variant':variant,'tag':tag,'rc':rc,'wall':time.monotonic()-start,'command':cmd,'timeout':timeout}
    if rc==0:
        record['mean'],record['loops']=read_result(target)
    state['records'].append(record)
    (OUT/'cohort-state.json').write_text(json.dumps(state,indent=2)+'\n')
    print(name,tag,variant,rc,round(record['wall'],2),record.get('mean'),flush=True)
    return record

for name in NAMES:
    pilot=run(name,'main','pilot',1 if name.startswith('networkx') else None)
    if pilot['rc']:
        # Retain failed controls and still test candidates with a fixed fallback.
        loops=1
    else: loops=pilot['loops']
    for block,order in enumerate(state['orders']):
        for variant in order: run(name,variant,str(block),loops)
assert {k:hashlib.sha256(p.read_bytes()).hexdigest() for k,p in BINARIES.items()}==HASHES
state['identity_verified_after']=True
(OUT/'cohort-state.json').write_text(json.dumps(state,indent=2)+'\n')
