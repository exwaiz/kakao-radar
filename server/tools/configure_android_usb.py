"""Provision the app's explicitly selected Kakao rooms over Linux ADB."""
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from uuid import UUID, uuid4

from pi_paths import DATA_ROOT, PROJECT_ROOT, STATE_ROOT

PACKAGE = "dev.kakaoradar.collector"


def main():
    adb = os.environ.get("ANDROID_ADB") or shutil.which("adb")
    if not adb:
        raise SystemExit("Install Android platform-tools and ensure adb is on PATH.")
    serial = os.environ.get("RADAR_ANDROID_SERIAL")
    target = [adb] + (["-s", serial] if serial else [])
    devices = subprocess.check_output([adb, "devices"], text=True).splitlines()[1:]
    ready = [line.split()[0] for line in devices if "\tdevice" in line]
    if not serial:
        if len(ready) != 1:
            raise SystemExit("Connect exactly one authorized Android device or set RADAR_ANDROID_SERIAL.")
        serial = ready[0]
        target = [adb, "-s", serial]
    elif serial not in ready:
        raise SystemExit("The requested Android device is not connected and authorized.")

    STATE_ROOT.mkdir(parents=True, exist_ok=True)
    os.chmod(STATE_ROOT, 0o700)
    identity = STATE_ROOT / "device.json"
    installed = subprocess.run(target + ["shell", "pm", "path", PACKAGE],
                               text=True, capture_output=True).returncode == 0
    if installed:
        prefs_result = subprocess.run(
            target + ["shell", "run-as", PACKAGE, "cat", "shared_prefs/collector.xml"],
            text=True, capture_output=True)
        if prefs_result.returncode == 0:
            prefs = ET.fromstring(prefs_result.stdout)
            value = next((el.text or "[]" for el in prefs if el.attrib.get("name") == "bindings_v2"), "[]")
            rooms = sorted({str(UUID(item["room_id"])) for item in json.loads(value)})
        elif identity.exists():
            # Fresh install has no preferences yet; reuse the already provisioned selection.
            rooms = sorted({str(UUID(room)) for room in json.loads(identity.read_text(encoding="utf-8")).get("rooms", [])})
        else:
            raise SystemExit("Select the intended Kakao rooms in the Android app before provisioning.")
    elif identity.exists():
        # Reuse previously selected rooms when a user intentionally removed the old app
        # before installing a differently signed build.
        rooms = sorted({str(UUID(room)) for room in json.loads(identity.read_text(encoding="utf-8")).get("rooms", [])})
    else:
        raise SystemExit("Install the existing app and select intended Kakao rooms before first provisioning.")
    if not rooms:
        raise SystemExit("Select the intended Kakao rooms in the Android app before provisioning.")

    if identity.exists():
        device = json.loads(identity.read_text(encoding="utf-8"))
        old_rooms = set(device.get("rooms", []))
        # Migrate the old single-room file in place without rotating its token.
        if "room" in device and not old_rooms:
            old_rooms.add(str(UUID(device.pop("room"))))
        device["rooms"] = sorted(old_rooms | set(rooms))
    else:
        device = {"device": str(uuid4()), "token": secrets.token_urlsafe(48), "rooms": rooms}
    identity.write_text(json.dumps(device), encoding="utf-8")
    identity.chmod(0o600)
    subprocess.run(["chown", "kakaoradar:", str(identity)], check=True)

    # Run PostgreSQL peer-authenticated provisioning under the service account.
    helper = PROJECT_ROOT / "server/tools/provision_pi_rooms.py"
    service_python = STATE_ROOT / "venv/bin/python"
    if not service_python.exists():
        raise SystemExit("Install the Pi runtime before provisioning selected rooms.")
    subprocess.run(["runuser", "-u", "kakaoradar", "--", str(service_python), str(helper), str(identity)], check=True)
    if "--install" in sys.argv:
        cert = STATE_ROOT / "local-cert.pem"
        apk = PROJECT_ROOT / "android/app/build/outputs/apk/debug/app-debug.apk"
        if not cert.exists() or not apk.exists():
            raise SystemExit("Build the debug APK and install local HTTPS before using --install.")
        # Install first so run-as can write the private setup file on fresh installs too.
        subprocess.run(target + ["install", "-r", str(apk)], check=True)
        subprocess.run(target + ["shell", "run-as", PACKAGE, "mkdir", "-p", "files"], check=True)
        setup = {**device, "server": "https://localhost:8443", "ca_pem": cert.read_text(encoding="utf-8")}
        subprocess.run(target + ["shell", "run-as", PACKAGE, "tee", "files/sync-setup.json"],
                       input=json.dumps(setup).encode(), check=True, capture_output=True)
        subprocess.run(target + ["reverse", "tcp:8443", "tcp:8443"], check=True)
        # Ensure Application.onCreate consumes the one-use private setup file.
        subprocess.run(target + ["shell", "am", "force-stop", PACKAGE], check=True)
        subprocess.run(target + ["shell", "cmd", "notification", "allow_listener",
                                 PACKAGE + "/dev.kakaoradar.collector.CollectorService"], check=True)
        subprocess.run(target + ["shell", "am", "start", "-n", PACKAGE + "/.MainActivity"],
                       check=True, capture_output=True)
        print("App installed; ADB HTTPS reverse ready.")
    else:
        print("Selected room IDs provisioned; no app data was changed.")


if __name__ == "__main__":
    main()
