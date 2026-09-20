"""Compare native string methods using baseline and modified interpreters.

Use the same build options for both interpreters. Pass --warm to materialize
the input's FSR before timing, or --fsr to use FSR-primary str subclasses.
Report median process CPU nanoseconds per call
and the increase in retained input size; output allocations are not included
in that size. These small measurements are exploratory, not a pyperformance
replacement.
"""

import sys
import time

if sys.argv[1:] not in ([], ['--warm'], ['--fsr']):
    raise SystemExit('usage: bench_unicode_methods.py [--warm | --fsr]')
warm = '--warm' in sys.argv[1:]


class Str(str):
    pass


def make_string(raw):
    value = raw.decode()
    return Str(value) if '--fsr' in sys.argv[1:] else value


samples = {
    'ascii': 'abc def\tghi\n' * 256,
    'latin1': 'é' * 4096,
    'mixed': ('a' * 63 + '😀') * 64,
    'japanese': '日本語\t😀\n' * 512,
}
operations = {
    'contains': lambda s: '😀' in s,
    'find': lambda s: s.find('😀'),
    'rfind': lambda s: s.rfind('😀'),
    'count': lambda s: s.count('😀'),
    'replace': lambda s: s.replace('a', 'X'),
    'startswith': lambda s: s.startswith('日本'),
    'endswith': lambda s: s.endswith('😀'),
    'split': lambda s: s.split('😀'),
    'split_ws': lambda s: s.split(),
    'rsplit_ws': lambda s: s.rsplit(),
    'partition': lambda s: s.partition('😀'),
    'strip': lambda s: s.strip(),
    'slice': lambda s: s[10:-10],
    'join': lambda s: s.join([s, s]),
    'repeat': lambda s: s*3,
    'center': lambda s: s.center(len(s)+10, '日'),
    'expandtabs': lambda s: s.expandtabs(4),
    'splitlines': lambda s: s.splitlines(),
    'isalpha': lambda s: s.isalpha(),
    'upper': lambda s: s.upper(),
    'lower': lambda s: s.lower(),
    'title': lambda s: s.title(),
    'capitalize': lambda s: s.capitalize(),
    'swapcase': lambda s: s.swapcase(),
    'casefold': lambda s: s.casefold(),
}
for name, text in samples.items():
    raw = text.encode()
    for opname, operation in operations.items():
        timings = []
        for _ in range(3):
            pool = [make_string(raw) for _ in range(80)]
            if warm:
                for s in pool:
                    s[0]
            start = time.process_time_ns()
            for s in pool:
                operation(s)
            timings.append((time.process_time_ns()-start)/len(pool))
        s = make_string(raw)
        if warm:
            s[0]
        size = sys.getsizeof(s)
        operation(s)
        print(name, opname, round(sorted(timings)[1]), sys.getsizeof(s)-size)
