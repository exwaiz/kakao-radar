import os
from pathlib import Path
import secrets
import subprocess

root = Path('/mnt/c/Users/exwai/Documents/Codex/2026-09-16/new-chat')
server = root / 'outputs/kakao-radar-wsl/server'
private_env = root / 'outputs/kakao-radar-fixed/.env.local'
state = server / '.state'
state.mkdir(exist_ok=True)
runtime = state / 'runtime.env'
if not runtime.exists():
    runtime.write_text('RADAR_DATABASE_URL=postgresql:///radar?user=kakaoradar&host=/var/run/postgresql\n'
                       'RADAR_ANALYSIS_PROVIDER=openai\nRADAR_DELIVERY_PROVIDER=telegram\n'
                       'RADAR_DIGEST_LINK_SECRET=' + secrets.token_urlsafe(48) + '\n',encoding='utf-8')

def pg(query):
    return subprocess.check_output(['runuser','-u','postgres','--','psql','-At','-c',query],text=True).strip()
if pg("SELECT count(*) FROM pg_roles WHERE rolname='kakaoradar'") == '0':
    pg('CREATE ROLE kakaoradar LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE')
for name in ('radar','radar_integration_test'):
    if pg("SELECT count(*) FROM pg_database WHERE datname='"+name+"'") == '0':
        pg('CREATE DATABASE '+name+' OWNER kakaoradar')

for name, component in [('api','api'),('analysis','analysis'),('retention','retention'),('delivery','delivery')]:
    unit = f'''[Unit]
Description=Kakao Radar {component}
After=postgresql.service network-online.target
Wants=postgresql.service

[Service]
Type=simple
User=kakaoradar
WorkingDirectory={server}
Environment=PYTHONDONTWRITEBYTECODE=1
EnvironmentFile={runtime}
ExecStart=/opt/kakao-radar/venv/bin/python tools/runtime.py {component} --private-env {private_env}
Restart=always
RestartSec=10
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
'''
    Path('/etc/systemd/system/kakao-radar-'+name+'.service').write_text(unit)

subprocess.run(['systemctl','daemon-reload'],check=True)
subprocess.run(['systemctl','enable','--now','kakao-radar-api','kakao-radar-retention'],check=True)
print('WSL database, localhost-only API and retention installed; no public tunnel; analysis/delivery await checks')
