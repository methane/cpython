import hashlib
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
prefix = os.environ.get('SCREEN_PREFIX', '')
variants = sys.argv[1:] or ['trace', 'prototype', 'before']
records = []
for block in range(3):
    order = variants[block % len(variants):] + variants[:block % len(variants)]
    for variant in order:
        binary = OUT / 'main-build/python' if variant.startswith('main') else ROOT / 'build-method-jit' / ('python-' + variant.removesuffix('-off'))
        digest = hashlib.sha256(binary.read_bytes()).hexdigest()
        target = OUT / f'{prefix}go-{block}-{variant}.json'
        assert not target.exists(), target
        cmd = ['taskset', '-c', '2', str(binary), str(ROOT/'benchmarks/go.py'), '--warmups', '5', '--values', '20', '--json']
        start = time.monotonic()
        result = subprocess.run(cmd, env={**os.environ, 'PYTHON_JIT':'0' if variant.endswith('-off') else '1', 'PYTHONPYCACHEPREFIX':f'/tmp/method-perf-{variant}'}, capture_output=True, text=True, timeout=15)
        (OUT / f'{prefix}go-{block}-{variant}.log').write_text(result.stderr)
        if result.returncode:
            print(variant, result.returncode, result.stderr, flush=True)
            continue
        target.write_text(result.stdout)
        data = json.loads(result.stdout)
        record = {'block':block, 'variant':variant, 'sha256':digest, 'mean':statistics.mean(data['samples_seconds']), 'wall':time.monotonic()-start, 'command':cmd}
        records.append(record)
        print(record, flush=True)
        assert hashlib.sha256(binary.read_bytes()).hexdigest() == digest
        (OUT/(prefix+'screen-'+'-'.join(variants)+'.json')).write_text(json.dumps(records,indent=2)+'\n')
