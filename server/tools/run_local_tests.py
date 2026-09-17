"""Run tests on a dedicated local PostgreSQL cluster; never use the M2 DB.

Example: python tools/run_local_tests.py --postgres-bin /path/to/pgsql/bin
The cluster is localhost-only, uses synthetic fixtures, and stops in finally.
"""
import argparse
import os
from pathlib import Path
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--postgres-bin", required=True, type=Path)
    parser.add_argument("--port", type=int, default=55329)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    state = root / ".state" / "m3-test-postgres"
    state.mkdir(parents=True, exist_ok=True)
    data = state / "data"
    suffix = ".exe" if os.name == "nt" else ""
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1")
    # Portable Windows PostgreSQL ships its shared libraries next to the binaries.
    env["PATH"] = str(args.postgres_bin.resolve()) + os.pathsep + env.get("PATH", "")

    def pg(tool, *arguments, check=True):
        return subprocess.run([str(args.postgres_bin / (tool + suffix)), *map(str, arguments)],
                              cwd=root, env=env, check=check,
                              creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)

    if not (data / "PG_VERSION").exists():
        pg("initdb", "-D", data, "-U", "radar_test", "--auth=trust", "--encoding=UTF8", "--locale=C")
    started = False
    try:
        pg("pg_ctl", "-D", data, "-l", state / "postgres.log", "-o", f"-h 127.0.0.1 -p {args.port}", "-w", "start")
        started = True
        import psycopg
        with psycopg.connect(f"postgresql://radar_test@127.0.0.1:{args.port}/postgres", autocommit=True) as db:
            if not db.execute("SELECT 1 FROM pg_database WHERE datname='radar_m3_test'").fetchone():
                db.execute("CREATE DATABASE radar_m3_test")
        env["RADAR_TEST_DATABASE_URL"] = f"postgresql://radar_test@127.0.0.1:{args.port}/radar_m3_test"
        result = subprocess.run([sys.executable, "-m", "pytest", "-q", "--junitxml=.state/m3-tests.xml"], cwd=root, env=env)
        if result.returncode == 0:
            result = subprocess.run([sys.executable,"tools/demo_m3.py"],cwd=root,env=env)
    finally:
        if started:
            pg("pg_ctl", "-D", data, "-m", "fast", "-w", "stop")
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
