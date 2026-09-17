#!/usr/bin/env python3
"""Exercise SQLAlchemy's declarative ORM using an in-memory SQLite database.

Standalone adaptation of
pyperformance/data-files/benchmarks/bm_sqlalchemy_declarative/run_benchmark.py.
Requires SQLAlchemy; the original benchmark pins SQLAlchemy==1.4.19.
Install it into the Python being measured with:
    python -m pip install SQLAlchemy==1.4.19

One operation inserts 100 people and addresses, committing each object
separately, then loads all people 100 times. --rows changes both counts.
Database setup, deletion of previous rows and result validation are untimed.
Run with --help for the spectral_norm.py-compatible timing options.
"""

from __future__ import annotations

import argparse
import json
import platform
import sqlite3
import statistics
import sys
import time

import sqlalchemy
from sqlalchemy import Column, ForeignKey, Integer, String, create_engine
from sqlalchemy.orm import declarative_base, relationship, sessionmaker


BENCHMARK = "sqlalchemy_declarative"
Base = declarative_base()


class Person(Base):
    __tablename__ = "person"
    id = Column(Integer, primary_key=True)
    name = Column(String(250), nullable=False)


class Address(Base):
    __tablename__ = "address"
    id = Column(Integer, primary_key=True)
    street_name = Column(String(250))
    street_number = Column(String(250))
    post_code = Column(String(250), nullable=False)
    person_id = Column(Integer, ForeignKey("person.id"))
    person = relationship(Person)


def benchmark(session, npeople):
    for i in range(npeople):
        new_person = Person(name="name %i" % i)
        session.add(new_person)
        session.commit()

        new_address = Address(post_code="%05i" % i, person=new_person)
        session.add(new_address)
        session.commit()

    for i in range(npeople):
        session.query(Person).all()


def run_loops(session, loops: int, npeople: int) -> float:
    elapsed = 0.0
    for _ in range(loops):
        session.query(Address).delete(synchronize_session=False)
        session.query(Person).delete(synchronize_session=False)

        start = time.perf_counter()
        benchmark(session, npeople)
        elapsed += time.perf_counter() - start
    return elapsed


def check_result(session, npeople: int):
    people = session.query(Person.id, Person.name).order_by(Person.id).all()
    addresses = session.query(
        Address.id, Address.person_id, Address.post_code,
        Address.street_name, Address.street_number,
    ).order_by(Address.id).all()
    expected_people = [(i + 1, "name %i" % i) for i in range(npeople)]
    expected_addresses = [
        (i + 1, i + 1, "%05i" % i, None, None) for i in range(npeople)
    ]
    if people != expected_people or addresses != expected_addresses:
        raise RuntimeError("SQLAlchemy person/address rows or relationships are invalid")
    return {
        "people": len(people),
        "addresses": len(addresses),
        "person_id_sum": sum(row[1] for row in addresses),
        "post_code_sum": sum(int(row[2]) for row in addresses),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--loops", type=int, default=1,
        help="operations per measured value (default: 1)",
    )
    parser.add_argument(
        "--warmups", type=int, default=3, help="unmeasured warmup values (default: 3)"
    )
    parser.add_argument(
        "--values", type=int, default=10, help="measured values (default: 10)"
    )
    parser.add_argument(
        "--rows", type=int, default=100, help="number of people and addresses (default: 100)"
    )
    parser.add_argument(
        "--json", action="store_true", help="write machine-readable output"
    )
    args = parser.parse_args()
    if args.loops < 1:
        parser.error("--loops must be positive")
    if args.warmups < 0:
        parser.error("--warmups must be non-negative")
    if args.values < 1:
        parser.error("--values must be positive")
    if args.rows < 1:
        parser.error("--rows must be positive")
    return args


def format_duration(seconds: float) -> str:
    if seconds >= 1.0:
        return f"{seconds:.6f} sec"
    return f"{seconds * 1_000:.3f} ms"


def main() -> None:
    args = parse_args()
    engine = create_engine("sqlite://")
    try:
        Base.metadata.create_all(engine)
        DBSession = sessionmaker(bind=engine)
        with DBSession() as session:
            for _ in range(args.warmups):
                run_loops(session, args.loops, args.rows)
                check_result(session, args.rows)

            samples = []
            checksum = None
            for _ in range(args.values):
                elapsed = run_loops(session, args.loops, args.rows)
                checksum = check_result(session, args.rows)
                samples.append(elapsed / args.loops)
    finally:
        engine.dispose()

    jit = getattr(sys, "_jit", None)
    workload = (
        f"insert {args.rows} people and addresses, commit each object, "
        f"load all people {args.rows} times"
    )
    output = {
        "benchmark": BENCHMARK,
        "runtime": f"Python {platform.python_version()} "
        f"({platform.python_implementation()})",
        "executable": sys.executable,
        "python_version": sys.version,
        "jit_enabled": jit.is_enabled() if jit is not None else None,
        "sqlalchemy_version": sqlalchemy.__version__,
        "sqlite_version": sqlite3.sqlite_version,
        "workload": workload,
        "rows": args.rows,
        "loops": args.loops,
        "warmups": args.warmups,
        "values": args.values,
        "median_seconds": statistics.median(samples),
        "minimum_seconds": min(samples),
        "samples_seconds": samples,
        "checksum": checksum,
    }
    if args.json:
        print(json.dumps(output, indent=2))
        return

    print(output["runtime"])
    print(f"SQLAlchemy {sqlalchemy.__version__}, SQLite {sqlite3.sqlite_version}")
    print(f"{BENCHMARK}: {workload}")
    print(f"median: {format_duration(output['median_seconds'])}")
    print(f"minimum: {format_duration(output['minimum_seconds'])}")
    print("values: " + ", ".join(format_duration(value) for value in samples))


if __name__ == "__main__":
    main()
