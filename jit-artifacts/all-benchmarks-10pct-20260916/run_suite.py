"""Compare the unchanged standalone workloads using matched process blocks."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import resource
import signal
import statistics
import subprocess
import time

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
DEPS = OUT/'shared-deps'
MAIN = ROOT/'jit-artifacts/method-perf-20260916/main-build/python'
LOOPS = {'bpe_tokeniser':1, 'btree':1, 'deltablue':32, 'go':1,
         'hexiom':16, 'raytrace':1, 'spectral_norm':1, 'sqlalchemy_declarative':1}

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def dependency_digest():
    result = hashlib.sha256()
    for path in sorted(DEPS.rglob('*')):
        if path.is_file() and '__pycache__' not in path.parts and path.suffix != '.pyc':
            result.update(str(path.relative_to(DEPS)).encode())
            result.update(bytes.fromhex(digest(path)))
    return result.hexdigest()

def extension_identities(binary):
    builddir = binary.parent / (binary.parent/'pybuilddir.txt').read_text().strip()
    return {str(path.relative_to(binary.parent)): digest(path)
            for path in sorted(builddir.glob('*.so'))}

def host_snapshot():
    rows = [line.split() for line in Path('/proc/stat').read_text().splitlines()]
    result = {'monotonic': time.monotonic(), 'cpu_ticks': {
        row[0]: list(map(int, row[1:])) for row in rows
        if row[0] in ('cpu2', 'cpu3')}, 'clock_ticks': os.sysconf('SC_CLK_TCK')}
    for cpu in (2, 3):
        try:
            result[f'cpu{cpu}_instant_khz'] = int(Path(
                f'/sys/devices/system/cpu/cpu{cpu}/cpufreq/scaling_cur_freq').read_text())
        except OSError:
            pass
    return result

def worker_cgroup(pid):
    try:
        return Path(f'/proc/{pid}/cgroup').read_text()
    except OSError as exc:
        return {'unavailable': str(exc)}

p=argparse.ArgumentParser()
p.add_argument('--candidate',default='build-method-jit/python-goal-start')
p.add_argument('--tag',required=True)
p.add_argument('--control', type=Path, default=MAIN)
p.add_argument('--blocks',type=int,default=3)
p.add_argument('--warmups',type=int,default=3)
p.add_argument('--values',type=int,default=7)
p.add_argument('--names',nargs='+',default=list(LOOPS))
a=p.parse_args()
binaries={'main':(ROOT/a.control).absolute(),'candidate':(ROOT/a.candidate).absolute()}
identities={k:digest(v) for k,v in binaries.items()}
extensions={k:extension_identities(v) for k,v in binaries.items()}
assert all(extensions.values())
dependencies = dependency_digest()
scripts={p.stem:digest(p) for p in sorted((ROOT/'benchmarks').glob('*.py'))}
assert set(scripts)==set(LOOPS), scripts
state={'tag':a.tag,'control_is_main':binaries['main']==MAIN,'binaries':{k:str(v) for k,v in binaries.items()},
       'sha256':identities,'extensions_sha256':extensions,
       'workloads':scripts,'loops':LOOPS,'cpu':2,
       'dependencies':{'path':str(DEPS),'sha256':dependencies},
       'warmups':a.warmups,'values':a.values,'records':[]}
state_path=OUT/f'{a.tag}-state.json'
assert not state_path.exists(),state_path
state_path.write_text(json.dumps(state,indent=2)+'\n')
for block in range(a.blocks):
    for name in a.names:
        for variant in (['main','candidate'] if block%2==0 else ['candidate','main']):
            target=OUT/f'{a.tag}-{block}-{name}-{variant}.json'
            cmd=['taskset','-c','2',str(binaries[variant]),str(ROOT/'benchmarks'/f'{name}.py'),
                 '--loops',str(LOOPS[name]),'--warmups',str(a.warmups),'--values',str(a.values),'--json']
            env={**os.environ,'PYTHONPATH':str(DEPS),'PYTHON_JIT':'1','PYTHONHASHSEED':str(block),
                 'PYTHONPYCACHEPREFIX':f'/tmp/jit-all-goal-{a.tag}-{variant}'}
            before = host_snapshot()
            usage_before = resource.getrusage(resource.RUSAGE_CHILDREN)
            start=time.monotonic()
            with target.open('w') as stdout, target.with_suffix('.log').open('w') as stderr:
                proc=subprocess.Popen(cmd,env=env,stdout=stdout,stderr=stderr,start_new_session=True)
                cgroup = worker_cgroup(proc.pid)
                try: rc=proc.wait(timeout=120)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid,signal.SIGKILL);proc.wait();rc=124
            usage_after = resource.getrusage(resource.RUSAGE_CHILDREN)
            r={'block':block,'name':name,'variant':variant,'rc':rc,
               'wall':time.monotonic()-start,'command':cmd,'hashseed':block}
            r['host_before'] = before
            r['host_after'] = host_snapshot()
            r['worker_cgroup'] = cgroup
            r['child_usage_delta'] = {key: getattr(usage_after, key) - getattr(usage_before, key)
                for key in ('ru_utime', 'ru_stime', 'ru_minflt', 'ru_majflt',
                            'ru_nvcsw', 'ru_nivcsw')}
            if not rc:
                data=json.loads(target.read_text());r['mean']=statistics.mean(data['samples_seconds']);r['checksum']=data['checksum'];r['sqlalchemy_version']=data.get('sqlalchemy_version');r['sqlite_version']=data.get('sqlite_version')
            state['records'].append(r)
            state_path.write_text(json.dumps(state,indent=2)+'\n')
            print(block,name,variant,rc,r.get('mean'),flush=True)
assert dependency_digest()==dependencies
assert {k:digest(v) for k,v in binaries.items()}==identities
assert {k:extension_identities(v) for k,v in binaries.items()}==extensions
assert {p.stem:digest(p) for p in sorted((ROOT/'benchmarks').glob('*.py'))}==scripts
summary={}
for name in a.names:
    pairs=[]
    for block in range(a.blocks):
        rr={r['variant']:r for r in state['records'] if r['name']==name and r['block']==block}
        if any(r['rc'] for r in rr.values()):continue
        assert rr['main']['checksum']==rr['candidate']['checksum'], name
        for version in ('sqlalchemy_version', 'sqlite_version'):
            assert rr['main'][version]==rr['candidate'][version], (name,version)
        pairs.append(rr['candidate']['mean']/rr['main']['mean'])
    summary[name]={'ratios':pairs,'ratio':statistics.geometric_mean(pairs) if pairs else None,
                   'complete':len(pairs)==a.blocks}
state['identity_verified_after']=True
state['summary']=summary
state_path.write_text(json.dumps(state,indent=2)+'\n')
print(json.dumps(summary,indent=2),flush=True)
