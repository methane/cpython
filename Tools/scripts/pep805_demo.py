"""Demonstrate PEP 805 ownership, transfer, and protected sharing.

Run from the CPython source tree with ``./python Tools/scripts/pep805_demo.py``.
The script asserts its results, so a failed PEP 805 operation exits nonzero.
"""

import threading


def main():
    # Freezing preserves identity and makes this configuration shareable.
    config = {"factor": 3}
    frozen = freeze(config)
    assert frozen is config
    assert config.__shareable__ is threading.Shareable.IMMUTABLE

    jobs = [threading.Channel() for _ in range(2)]
    reports = threading.Channel()
    lock = threading.Lock()
    with lock:
        totals = lock.protect({"jobs": 0})

    # Each Channel.put() makes a shallow copy of a local list.  Mutating the
    # source afterwards must not change the copy claimed by a worker.
    for index, start in enumerate(range(0, 40, 10)):
        chunk = list(range(start, start + 10))
        jobs[index % len(jobs)].put(chunk)
        chunk.append(-1)

    private = [42]

    def worker(inbox):
        # A local value owned by Main cannot be read in another ThreadGroup.
        try:
            private[0]
        except IllegalThreadAccessException:
            local_access_denied = True
        else:
            local_access_denied = False

        subtotal = count = 0
        while True:
            chunk = inbox.get()
            if chunk is None:
                break
            subtotal += config["factor"] * sum(value * value for value in chunk)
            count += 1
            with lock:
                totals["jobs"] += 1
        reports.put((subtotal, count, local_access_denied,
                     threading.current_thread().group))

    workers = [threading.Thread(target=worker, args=(inbox,),
                                group=threading.ThreadGroup())
               for inbox in jobs]
    for inbox in jobs:
        inbox.put(None)
    for thread in workers:
        thread.start()
    for thread in workers:
        thread.join()

    results = [reports.get() for _ in workers]
    actual = sum(subtotal for subtotal, _, _, _ in results)
    expected = config["factor"] * sum(value * value for value in range(40))
    assert actual == expected, (actual, expected)
    assert sorted(count for _, count, _, _ in results) == [2, 2]
    assert all(denied for _, _, denied, _ in results)
    assert {group for _, _, _, group in results} == {
        thread.group for thread in workers}
    assert all(group is not threading.current_thread().group
               for _, _, _, group in results)
    assert private == [42]

    with lock:
        assert totals["jobs"] == 4
    try:
        totals["jobs"]
    except UnprotectedAccessException:
        protected_access_denied = True
    else:
        protected_access_denied = False
    assert protected_access_denied

    print(f"two ThreadGroups processed 4 chunks; weighted square sum = {actual}")
    print("foreign LOCAL access: denied")
    print("PROTECTED access without lock: denied")


if __name__ == "__main__":
    main()
