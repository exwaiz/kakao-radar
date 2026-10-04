"""Install localhost-only HTTPS for Android's adb reverse tunnel."""
import os
from pathlib import Path
import subprocess
import sys

from pi_paths import PRIVATE_ENV, SERVER_ROOT, STATE_ROOT


def main():
    if os.geteuid() != 0:
        raise SystemExit("Run with sudo after install_pi_runtime.py.")
    cert, key = STATE_ROOT / "local-cert.pem", STATE_ROOT / "local-key.pem"
    STATE_ROOT.mkdir(parents=True, exist_ok=True)
    if not cert.exists() and not key.exists():
        subprocess.run([
            "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "3650",
            "-subj", "/CN=Kakao Radar localhost",
            "-addext", "subjectAltName=DNS:localhost",
            "-addext", "basicConstraints=critical,CA:TRUE",
            "-keyout", str(key), "-out", str(cert),
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        key.chmod(0o600)
        cert.chmod(0o644)
    if not cert.exists() or not key.exists():
        raise SystemExit("Only one local TLS file exists; preserve it and inspect the pair before continuing.")
    service_python = STATE_ROOT / "venv/bin/python"
    if not service_python.exists():
        service_python = Path(sys.executable)
    unit = f'''[Unit]
Description=Kakao Radar USB local HTTPS
After=postgresql.service kakao-radar-api.service
Wants=postgresql.service

[Service]
Type=simple
User=kakaoradar
WorkingDirectory={SERVER_ROOT}
EnvironmentFile={STATE_ROOT / 'runtime.env'}
Environment=RADAR_DATA_DIR={STATE_ROOT.parent}
ExecStart={service_python} tools/runtime.py api --private-env {PRIVATE_ENV} --host 127.0.0.1 --port 8443 --ssl-certfile {cert} --ssl-keyfile {key}
Restart=always
RestartSec=10
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
'''
    Path("/etc/systemd/system/kakao-radar-local-https.service").write_text(unit, encoding="utf-8")
    subprocess.run(["chown", "kakaoradar:", str(cert), str(key)], check=True)
    subprocess.run(["systemctl", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "enable", "--now", "kakao-radar-local-https"], check=True)
    print("USB HTTPS listens on 127.0.0.1:8443; adb reverse is required; no public listener was opened.")


if __name__ == "__main__":
    main()
