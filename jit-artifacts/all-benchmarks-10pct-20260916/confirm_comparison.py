"""Report prespecified eight/twelve-block confirmation, without discarding runs."""
import argparse
import json
import math
from pathlib import Path
import statistics

p = argparse.ArgumentParser()
p.add_argument('tag')
a = p.parse_args()
out = Path(__file__).resolve().parent
state = json.loads((out / f'{a.tag}-state.json').read_text())
assert state['identity_verified_after'] and state['control_is_main']
assert len(state['summary']) == 8
blocks = len({r['block'] for r in state['records']})
critical = {8: 2.364624251, 12: 2.200985160}[blocks]
lines = [f'# 固定バイナリの確認計測: {a.tag}', '',
         f'{blocks}ブロック、CPU 2、実行順交互。各プロセスでwarmup {state["warmups"]}回、'
         f'計測{state["values"]}回。全サンプルを使用。', '',
         '時間比は各ブロックのcandidate/mainの幾何平均。95%区間はブロックごとの'
         '対数比に対するStudent t区間。プロセス内のサンプルを独立反復として数えない。', '',
         '判定は各項目の区間上限が0.90以下。区間はこの固定バイナリ・CPUでの実行時の'
         '揺れに対するもので、再ビルド・別CPUでの再現性や8項目同時の95%保証ではない。', '',
         '| 項目 | 時間比 | 95%区間 | ブロック比範囲 | 上限≤0.90 |',
         '|---|---:|---:|---:|---|']
results = {}
for name, row in state['summary'].items():
    ratios = row['ratios']
    assert row['complete'] and len(ratios) == blocks
    logs = list(map(math.log, ratios))
    center = statistics.mean(logs)
    margin = critical * statistics.stdev(logs) / math.sqrt(blocks)
    lo, hi = math.exp(center-margin), math.exp(center+margin)
    ok = hi <= .90
    results[name] = {'ratio': math.exp(center), 'ci95': [lo, hi], 'passes': ok}
    lines.append(f'| {name} | {math.exp(center):.4f} | {lo:.4f}–{hi:.4f} | '
                 f'{min(ratios):.4f}–{max(ratios):.4f} | {"yes" if ok else "no"} |')
lines += ['', f'全8本の判定: {all(r["passes"] for r in results.values())}', '',
          f'生データ・バイナリと依存ファイルのSHA: [{a.tag}-state.json]({a.tag}-state.json)', '']
(out / f'{a.tag}-confirmation.md').write_text('\n'.join(lines))
(out / f'{a.tag}-confirmation.json').write_text(json.dumps(results, indent=2)+'\n')
print('\n'.join(lines))
