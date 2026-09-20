"""Compare UTF-8 and fixed-width string storage with the same build options.

Run with each interpreter under comparison. Timings include Python call overhead
and are exploratory; use a release build and a controlled host for performance
decisions. Sizes include the object and retained payloads, not allocator overhead.
"""

import sys
import time

samples = {
    'ascii': 'a' * 4096,
    'latin1': 'é' * 4096,
    'bmp': '日' * 4096,
    'nonbmp': '😀' * 4096,
    'mixed': 'a' * 4095 + '😀',
}

def measure(action, count=1000):
    values = []
    for _ in range(5):
        start = time.process_time_ns()
        for i in range(count):
            action()
        values.append((time.process_time_ns() - start) / count)
    return sorted(values)[2]

print({'version': sys.version, 'clock': 'process_time_ns', 'length': 4096})
for name, text in samples.items():
    raw = text.encode()
    s = raw.decode()
    fresh_size = sys.getsizeof(s)
    s[0]
    indexed_size = sys.getsizeof(s)
    peer = raw.decode()
    values = {
        'fresh_bytes': fresh_size,
        'indexed_bytes': indexed_size,
        'decode_ns': measure(lambda: raw.decode()),
        'index_warm_ns': measure(lambda: s[2048]),
        'encode_ns': measure(lambda: s.encode()),
        'concat_ns': measure(lambda: s + peer),
        'equal_ns': measure(lambda: s == peer),
    }
    pool = [raw.decode() for _ in range(100)]
    start = time.process_time_ns()
    for item in pool:
        item[0]
    values['index_first_ns'] = (time.process_time_ns() - start) / len(pool)
    pool = [raw.decode() for _ in range(100)]
    start = time.process_time_ns()
    for item in pool:
        hash(item)
    values['hash_first_ns'] = (time.process_time_ns() - start) / len(pool)
    print(name, values)
