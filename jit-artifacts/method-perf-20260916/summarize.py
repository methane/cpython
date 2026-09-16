import json, math, statistics
from pathlib import Path
O=Path(__file__).resolve().parent
s=json.loads((O/'cohort-state.json').read_text())
rows=[];failures=[]
for name in s['names']:
    records=[r for r in s['records'] if r['name']==name and r['tag']!='pilot']
    groups={v:[r for r in records if r['variant']==v] for v in s['binaries']}
    if any(len(g)!=2 or any(r['rc'] for r in g) for g in groups.values()):
        failures.append({'name':name,'runs':records});continue
    means={v:statistics.geometric_mean(r['mean'] for r in g) for v,g in groups.items()}
    paired={v:[groups[v][i]['mean']/groups['main'][i]['mean'] for i in range(2)] for v in ['before','candidate']}
    rows.append({'name':name,'means':means,'before/main':means['before']/means['main'],'candidate/main':means['candidate']/means['main'],'candidate/before':means['candidate']/means['before'],'paired':paired})
summary={'rows':rows,'failures':failures,'geomean':{key:statistics.geometric_mean(r[key] for r in rows) for key in ['before/main','candidate/main','candidate/before']} if rows else {}}
(O/'cohort-summary.json').write_text(json.dumps(summary,indent=2)+'\n')
lines=['# Fixed pyperformance cohort','',f'Completed paired workloads: {len(rows)}/{len(s["names"])}. Lower runtime ratios are better.','', '| Workload | Main (ms) | Before/main | Candidate/main | Candidate/before | Candidate/main block range |','|---|---:|---:|---:|---:|---:|']
for r in rows:
    lo,hi=min(r['paired']['candidate']),max(r['paired']['candidate'])
    lines.append(f'| {r["name"]} | {1000*r["means"]["main"]:.3f} | {r["before/main"]:.4f} | {r["candidate/main"]:.4f} | {r["candidate/before"]:.4f} | {lo:.4f}–{hi:.4f} |')
lines+=['',f'Geometric means: {summary["geomean"]}', '', 'Two independent processes per binary/workload, five measured values per process after three warmups. The range describes two paired process ratios; it is not a confidence interval. Pilot calibration results are excluded from the comparison. Each workload has equal geometric-mean weight.']
if failures:
    lines+=['','Incomplete workloads (excluded from paired aggregate, retained in raw data):']
    for f in failures:lines.append(f'- {f["name"]}: '+str([(r['variant'],r['tag'],r['rc']) for r in f['runs']]))
(O/'cohort-summary.md').write_text('\n'.join(lines)+'\n')
print('\n'.join(lines))
