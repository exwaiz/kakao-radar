import json
import os
from pathlib import Path
import subprocess
import sys
from uuid import UUID

root=Path('/mnt/c/Users/exwai/Documents/Codex/2026-09-16/new-chat')
server=root/'outputs/kakao-radar-wsl/server'
state=server/'.state'
sys.path.insert(0,str(server))
from radar_server.store import Store
device=json.loads((state/'device.json').read_text())
store=Store('postgresql:///radar?user=kakaoradar&host=/var/run/postgresql')
if '--provision' in sys.argv:
    store.migrate()
    store.provision(UUID(device['device']),UUID(device['room']),device['token'])
    print('WSL private device and selected room provisioned')
else:
    cert,key=state/'local-cert.pem',state/'local-key.pem'
    if not cert.exists():
        subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','365','-subj','/CN=Kakao Radar Local',
            '-addext','subjectAltName=DNS:localhost','-addext','basicConstraints=critical,CA:TRUE',
            '-keyout',str(key),'-out',str(cert)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    private_env=root/'outputs/kakao-radar-fixed/.env.local'
    unit=f'''[Unit]
Description=Kakao Radar USB local HTTPS
After=postgresql.service
Wants=postgresql.service
[Service]
User=kakaoradar
WorkingDirectory={server}
Environment=PYTHONDONTWRITEBYTECODE=1
EnvironmentFile={state/'runtime.env'}
ExecStart=/opt/kakao-radar/venv/bin/python tools/runtime.py api --private-env {private_env} --port 8443 --ssl-certfile {cert} --ssl-keyfile {key}
Restart=always
RestartSec=10
NoNewPrivileges=true
PrivateTmp=true
[Install]
WantedBy=multi-user.target
'''
    Path('/etc/systemd/system/kakao-radar-local-https.service').write_text(unit)
    subprocess.run(['systemctl','daemon-reload'],check=True)
    subprocess.run(['systemctl','enable','--now','kakao-radar-local-https'],check=True)
    print('Local HTTPS ready on loopback only; no public tunnel')
