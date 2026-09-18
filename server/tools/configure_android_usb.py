"""Provision only the already selected room; never export chats or print credentials."""
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
from uuid import uuid4, UUID
import xml.etree.ElementTree as ET

root=Path(__file__).resolve().parents[4]
os.environ['ANDROID_USER_HOME']=str(root/'work/android-user')
adb=[str(root/'work/android-tools/sdk/platform-tools/adb.exe'),'-s','FYZPL77XO799DAQO']
state=root/'outputs/kakao-radar-wsl/server/.state'
state.mkdir(exist_ok=True)
selected=ET.fromstring(subprocess.check_output(adb+['shell','run-as','dev.kakaoradar.collector','cat','shared_prefs/collector.xml']))
room=next(e.text for e in selected if e.attrib.get('name')=='room_id')
UUID(room)
path=state/'device.json'
if path.exists():
    device=json.loads(path.read_text())
    if device['room']!=room: raise SystemExit('Selected room changed; stop before provisioning')
else:
    device={'device':str(uuid4()),'room':room,'token':secrets.token_urlsafe(48)}
    path.write_text(json.dumps(device),encoding='utf-8')
if '--install' in sys.argv:
    ca=(state/'local-cert.pem').read_text()
    setup={**device,'server':'https://localhost:8443','ca_pem':ca}
    subprocess.run(adb+['shell',"run-as dev.kakaoradar.collector sh -c 'cat > files/sync-setup.json'"],input=json.dumps(setup).encode(),check=True,capture_output=True)
    subprocess.run(adb+['reverse','tcp:8443','tcp:8443'],check=True)
    apk=root/'outputs/kakao-radar-wsl/android/app/build/outputs/apk/debug/app-debug.apk'
    subprocess.run(adb+['install','-r',str(apk)],check=True)
    subprocess.run(adb+['shell','cmd','notification','allow_listener','dev.kakaoradar.collector/dev.kakaoradar.collector.CollectorService'],check=True)
    subprocess.run(adb+['shell','am','start','-n','dev.kakaoradar.collector/.MainActivity'],check=True,capture_output=True)
    print('Updated app; one-use setup applied; selected room preserved; USB HTTPS forwarding ready')
else:
    print('Existing selected room prepared for private device provisioning')
