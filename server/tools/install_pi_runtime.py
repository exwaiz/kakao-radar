"""Install the native PostgreSQL/systemd runtime on Raspberry Pi OS/Debian."""
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys

from pi_paths import DATA_ROOT, PRIVATE_ENV, SERVER_ROOT, STATE_ROOT


def run(*args):
    subprocess.run(args, check=True)


def pg(query):
    return subprocess.check_output(
        ["runuser", "-u", "postgres", "--", "psql", "-At", "-c", query], text=True
    ).strip()


def main():
    if os.geteuid() != 0:
        raise SystemExit("Run with sudo after installing PostgreSQL, Python 3.11+, and adb.")
    missing = [name for name in ("systemctl", "runuser", "psql", "openssl") if not shutil.which(name)]
    if missing:
        raise SystemExit("Install required system packages first: " + ", ".join(missing))

    service_user = "kakaoradar"
    if subprocess.run(["id", service_user], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode:
        run("useradd", "--system", "--home-dir", str(DATA_ROOT), "--create-home",
            "--shell", "/usr/sbin/nologin", service_user)
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    STATE_ROOT.mkdir(parents=True, exist_ok=True)
    PRIVATE_ENV.parent.mkdir(parents=True, exist_ok=True)
    if not PRIVATE_ENV.exists():
        PRIVATE_ENV.write_text(
            "OPENAI_API_KEY=\nRADAR_TELEGRAM_BOT_TOKEN=\nRADAR_TELEGRAM_CHAT_ID=\n"
            "RADAR_TELEGRAM_ADMIN_USER_ID=\nRADAR_NTFY_URL=\nRADAR_NTFY_TOPIC=\n"
            "RADAR_NTFY_TOKEN=\n", encoding="utf-8"
        )
        PRIVATE_ENV.chmod(0o600)
    runtime = STATE_ROOT / "runtime.env"
    if not runtime.exists():
        runtime.write_text(
            "RADAR_DATABASE_URL=postgresql:///radar?user=kakaoradar&host=/var/run/postgresql\n"
            "RADAR_DATA_DIR=" + str(DATA_ROOT) + "\n"
            "RADAR_ANALYSIS_PROVIDER=disabled\nRADAR_DELIVERY_PROVIDER=disabled\n"
            "RADAR_DIGEST_LINK_SECRET=" + secrets.token_urlsafe(48) + "\n",
            encoding="utf-8",
        )
        runtime.chmod(0o600)

    venv = STATE_ROOT / "venv"
    if not (venv / "bin/python").exists():
        run(sys.executable, "-m", "venv", str(venv))
    run(str(venv / "bin/pip"), "install", "-r", str(SERVER_ROOT / "requirements.txt"),
        "-c", str(SERVER_ROOT / "requirements-lock.txt"))

    if pg("SELECT count(*) FROM pg_roles WHERE rolname='kakaoradar'") == "0":
        pg("CREATE ROLE kakaoradar LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE")
    if pg("SELECT count(*) FROM pg_database WHERE datname='radar'") == "0":
        pg("CREATE DATABASE radar OWNER kakaoradar")
    # Existing databases are left intact, including ownership and all rows.
    run("chown", "-R", service_user + ":", str(DATA_ROOT))
    run("chown", "root:" + service_user, str(PRIVATE_ENV))
    run("chmod", "640", str(PRIVATE_ENV))
    run("chmod", "700", str(DATA_ROOT), str(STATE_ROOT))

    python = venv / "bin/python"
    unit = f'''[Unit]
Description=Kakao Radar local API
After=postgresql.service network-online.target
Wants=postgresql.service

[Service]
Type=simple
User={service_user}
WorkingDirectory={SERVER_ROOT}
EnvironmentFile={runtime}
Environment=RADAR_DATA_DIR={DATA_ROOT}
ExecStart={python} -m uvicorn radar_server.app:create_app --factory --host 127.0.0.1 --port 8000 --no-access-log --log-level warning
Restart=always
RestartSec=10
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
'''
    Path("/etc/systemd/system/kakao-radar-api.service").write_text(unit, encoding="utf-8")
    for component in ("analysis", "delivery", "telegram-commands"):
        worker_unit = f'''[Unit]
Description=Kakao Radar {component}
After=postgresql.service network-online.target
Wants=postgresql.service

[Service]
Type=simple
User={service_user}
WorkingDirectory={SERVER_ROOT}
EnvironmentFile={runtime}
ExecStart={python} tools/runtime.py {component} --private-env {PRIVATE_ENV}
Restart=always
RestartSec=10
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
'''
        Path(f"/etc/systemd/system/kakao-radar-{component}.service").write_text(
            worker_unit, encoding="utf-8"
        )
    run("systemctl", "daemon-reload")
    run("systemctl", "enable", "--now", "kakao-radar-api")
    print("Kakao Radar API installed on 127.0.0.1:8000; analysis and delivery remain disabled.")
    print("Worker units were written but left disabled. No retention service was installed.")
    print("No database was dropped or cleared.")


if __name__ == "__main__":
    main()
