"""Analyze complete balanced comparisons; retain all measured workers."""
from pathlib import Path
import hashlib,json,math,random,statistics as stats,sys
root=Path(sys.argv[1]).resolve()
for profile in ('ft','gil-pgo-lto'):
    work=root/profile
    state=json.loads((work/'state.json').read_text())
    suite=json.loads((work/'suite.json').read_text())
    assert state.get('finished') and state.get('identities_verified_after')
    blocks=state['protocol']['blocks'];processes=state['protocol']['processes']
    assert blocks>=2 and blocks%2==0
    rng=random.Random(20260920);results={};failures={}
    aggregate_bootstrap_logs=[0.0]*4000
    for spec,definition in sorted(suite['benchmarks'].items()):
        if suite['groups'][definition['group']]['returncode']:
            failures[spec]={'reason':'dependency preparation failed'};continue
        rows=[state['runs'].get(f'{block}:{spec}:{side}') for block in range(blocks) for side in ('main','candidate')]
        if any(not row or row['returncode'] for row in rows):
            failures[spec]={'reason':'incomplete specification','runs':rows};continue
        samples={}
        for row in rows:
            path=Path(row['output']);data=path.read_bytes()
            assert hashlib.sha256(data).hexdigest()==row['sha256'],path
            document=json.loads(data)
            for bench in document['benchmarks']:
                meta={**document.get('metadata',{}),**bench.get('metadata',{})}
                name=meta['name'];workers=[stats.mean(run['values']) for run in bench['runs'] if run.get('values')]
                assert len(workers)==processes,(spec,name,len(workers))
                assert math.isclose(stats.mean(workers),row['means'][name],rel_tol=1e-12),(spec,name)
                samples[name,row['block'],row['side']]=workers
        names=set(rows[0]['means'])
        assert all(set(row['means'])==names for row in rows)
        for name in sorted(names):
            pair_samples=[[samples[name,block,side] for side in ('main','candidate')] for block in range(blocks)]
            ratios=[stats.mean(b[1])/stats.mean(b[0]) for b in pair_samples]
            boot=[stats.geometric_mean(stats.mean(rng.choices(b[1],k=len(b[1])))/stats.mean(rng.choices(b[0],k=len(b[0]))) for b in pair_samples) for _ in range(4000)]
            for index,value in enumerate(boot):
                aggregate_bootstrap_logs[index]+=math.log(value)
            boot.sort()
            results[name]={'specification':spec,'ratio':stats.geometric_mean(ratios),'blocks':ratios,'ci95':[boot[100],boot[3899]],'workers':pair_samples,'median_sensitivity':stats.geometric_mean(stats.median(b[1])/stats.median(b[0]) for b in pair_samples)}
    aggregate_bootstrap=sorted(math.exp(value/len(results)) for value in aggregate_bootstrap_logs) if results else []
    result={'profile':profile,'rows':results,'failures':failures,'verified':True,'source':str(work/'state.json'),'protocol':state['protocol'],'geomean_completed':stats.geometric_mean(r['ratio'] for r in results.values()) if results else None,
            'geomean_ci95': [aggregate_bootstrap[100],aggregate_bootstrap[3899]] if results else None,
            'geomean_by_block': [stats.geometric_mean(r['blocks'][block] for r in results.values()) for block in range(blocks)] if results else [],
            'bootstrap': {'replicates':4000,'seed':20260920,'unit':'worker within each benchmark and ordered block','scope':'fixed set of completed benchmark results and fixed binaries'}}
    (work/'worker-analysis.json').write_text(json.dumps(result,indent=2)+'\n')
    print(profile,'completed results',len(results),'failed specifications',len(failures),'geomean',result['geomean_completed'])
    for name,row in sorted(results.items(),key=lambda item:item[1]['ratio'],reverse=True):
        print(f"{name:34s} {row['ratio']:.4f} [{row['ci95'][0]:.4f}, {row['ci95'][1]:.4f}]")
