"""Run tests on a dedicated M4 local PostgreSQL cluster; never use the M2/M3 DB.

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
    parser.add_argument("--state-dir", type=Path,
                        help="Test cluster directory; use a WSL ext4 path instead of /mnt/c")
    parser.add_argument("--port", type=int, default=55330)
    parser.add_argument("--serve", action="store_true", help="Keep the synthetic phone digest open for local UI verification")
    parser.add_argument("--tests-only", action="store_true", help="Skip optional demos after the test suite")
    parser.add_argument("--server-port", type=int, default=8004)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    state = args.state_dir.resolve() if args.state_dir else root / ".state" / "m4-test-postgres"
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
        server_options = f"-h 127.0.0.1 -p {args.port}"
        if os.name != "nt":
            # An unprivileged test account may not be allowed to create sockets
            # in the distribution-wide /var/run/postgresql directory.
            server_options += f" -k {state}"
        pg("pg_ctl", "-D", data, "-l", state / "postgres.log", "-o", server_options, "-w", "start")
        started = True
        import psycopg
        with psycopg.connect(f"postgresql://radar_test@127.0.0.1:{args.port}/postgres", autocommit=True) as db:
            if not db.execute("SELECT 1 FROM pg_database WHERE datname='radar_m4_test'").fetchone():
                db.execute("CREATE DATABASE radar_m4_test")
        env["RADAR_TEST_DATABASE_URL"] = f"postgresql://radar_test@127.0.0.1:{args.port}/radar_m4_test"
        result = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                                 "--junitxml=" + str(state / "m4-tests.xml")], cwd=root, env=env)
        if result.returncode == 0 and not args.tests_only:
            result = subprocess.run([sys.executable,"tools/demo_m3.py"],cwd=root,env=env)
        if result.returncode == 0 and not args.tests_only:
            command = [sys.executable,"tools/demo_m4.py"]
            if args.serve:
                command.extend(["--serve","--port",str(args.server_port)])
            result = subprocess.run(command,cwd=root,env=env)
    finally:
        if started:
            pg("pg_ctl", "-D", data, "-m", "fast", "-w", "stop")
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
