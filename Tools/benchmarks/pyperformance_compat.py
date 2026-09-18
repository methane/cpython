"""Audited compatibility patches for private pyperformance environments.

Never edit the cache: apply these only to fresh workload/venv copies and save
the returned before/after hashes in the experiment's preparation manifest.
"""

import hashlib


def replace(path, changes):
    original = path.read_bytes()
    source = original.decode()
    for old, new in changes:
        if source.count(old) != 1:
            raise RuntimeError(f"Review changed compatibility patch input: {path}")
        source = source.replace(old, new)
    patched = source.encode()
    path.write_bytes(patched)
    return {"path": str(path),
            "before": hashlib.sha256(original).hexdigest(),
            "after": hashlib.sha256(patched).hexdigest()}


def dependencies(site):
    patches = []
    cloudpickle = site / "cloudpickle/cloudpickle.py"
    if cloudpickle.exists():
        patches.append(replace(cloudpickle, [
            ('DELETE_GLOBAL = opcode.opmap["DELETE_GLOBAL"]',
             'DELETE_GLOBAL = opcode.opmap.get("DELETE_GLOBAL")'),
        ]))
    genshi = site / "genshi/template/astutil.py"
    if genshi.exists():
        patches.append(replace(genshi, [
            ('        clone = node.__class__()',
             '        clone = node.__class__(**{name: getattr(node, name)\n'
             '                                  for name in node._fields\n'
             '                                  if hasattr(node, name)})'),
        ]))
        patches.append(replace(site / "genshi/template/eval.py", [
            ('    ret = class_()\n'
             '    for attr, value in zip(ret._fields, args):\n'
             '        if attr in kwargs:\n'
             "            raise ValueError('Field set both in args and kwargs')\n"
             '        setattr(ret, attr, value)\n'
             '    for attr, value in kwargs:\n'
             '        setattr(ret, attr, value)\n'
             '    return ret',
             '    for attr, value in zip(class_._fields, args):\n'
             '        if attr in kwargs:\n'
             "            raise ValueError('Field set both in args and kwargs')\n"
             '        kwargs[attr] = value\n'
             '    return class_(**kwargs)'),
        ]))
    return patches


def workloads(directory):
    return [replace(directory / "benchmarks/bm_asyncio_websockets/run_benchmark.py", [
        ('async with websockets.server.serve(handler, "", 8001):\n'
         '        async with websockets.client.connect("ws://localhost:8001") as ws:',
         'async with websockets.server.serve(handler, "127.0.0.1", 0) as server:\n'
         '        port = server.sockets[0].getsockname()[1]\n'
         '        async with websockets.client.connect(f"ws://127.0.0.1:{port}") as ws:'),
    ])]
