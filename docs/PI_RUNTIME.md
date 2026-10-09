# Raspberry Pi runtime

This runbook replaces the laptop-specific WSL/Windows deployment. It targets Raspberry Pi OS/Debian 13 on 64-bit ARM. PostgreSQL and the API run on the Pi; the phone connects over authorized Wi-Fi ADB with `adb reverse`. The API binds to `127.0.0.1:8000`, and its local HTTPS endpoint binds to `127.0.0.1:8443`. No router or firewall port is opened.

## Prepare the Pi

Install the system packages:

```sh
sudo apt update
sudo apt install -y postgresql python3 python3-venv python3-dev build-essential libpq-dev openssl adb
```

Place this repository in a Linux filesystem path. Install the runtime and local HTTPS endpoint:

```sh
cd /path/to/kakao-radar
sudo python3 server/tools/install_pi_runtime.py
sudo python3 server/tools/install_pi_local_tls.py
```

The runtime creates the `kakaoradar` service account, a peer-authenticated `radar` database if absent, `/var/lib/kakao-radar`, and a Python virtual environment. It starts only the API and loopback HTTPS services. It writes analysis, delivery, and Telegram command systemd units but leaves them disabled. It never drops or clears a database and does not install or enable retention.

## Credentials

Keep values in `/etc/kakao-radar/credentials.env`, outside the checkout. The installer creates an empty template and sets it to `root:kakaoradar` mode `0640`, so only root and the service account can read it. To enable the already selected OpenAI and Telegram behavior, provide:

```dotenv
OPENAI_API_KEY=...
RADAR_TELEGRAM_BOT_TOKEN=...
RADAR_TELEGRAM_CHAT_ID=...
RADAR_TELEGRAM_ADMIN_USER_ID=...
```

The local database uses PostgreSQL peer authentication and needs no database password. ntfy and public digest links are optional and remain unset. Do not put credentials in Git, shell history, or command output.

## Android over Wi-Fi ADB

Authorize this Pi once over USB, then use Android Wireless debugging pairing (or `adb tcpip` on older devices). Keep the Pi and phone on a network that permits device-to-device traffic and check that `adb devices -l` shows the Wi-Fi transport as `device`. Set `RADAR_ANDROID_SERIAL` to that Wi-Fi serial when USB and Wi-Fi transports are both present. The v3 APK has no launcher Activity. Build it, then update the existing signed installation without deleting app data:

```sh
cd android && ./gradlew :app:assembleDebug
adb -s <phone-ip>:<port> install -r app/build/outputs/apk/debug/app-debug.apk
cd ..
python3 server/tools/radar_adb.py link --serial <phone-ip>:<port>
python3 server/tools/radar_adb.py status --serial <phone-ip>:<port>
```

The same signing certificate is required for an in-place update. The app keeps selected rooms, saved messages, upload queue, and encrypted device credentials. Never uninstall or clear app data to change versions. The Android `AdbControlReceiver` requires the shell-held `DUMP` permission; normal apps cannot call it. If Xiaomi blocks a cold broadcast after an update, the CLI starts a protected, invisible bootstrap Activity and retries automatically.

Use the CLI for all routine controls. `rooms` lists selected and discovered room IDs with names; selection is explicit and pauses collection until the newly selected room is provisioned on the Pi. The commands return JSON without message text or credentials:

```sh
python3 server/tools/radar_adb.py rooms --serial <phone-ip>:<port>
python3 server/tools/radar_adb.py room-select <candidate-id> --serial <phone-ip>:<port>
python3 server/tools/radar_adb.py collection-enable --serial <phone-ip>:<port>
python3 server/tools/radar_adb.py listener-rebind --serial <phone-ip>:<port>
python3 server/tools/radar_adb.py listener-reconnect --serial <phone-ip>:<port>
python3 server/tools/radar_adb.py sync-once --serial <phone-ip>:<port>
python3 server/tools/radar_adb.py sync-drain --serial <phone-ip>:<port>
python3 server/tools/radar_adb.py export-diagnostics --output /private/path/diagnostics.jsonl --serial <phone-ip>:<port>
```

`room-remove`, `collection-disable`, `sync-enable`, and `sync-disable` are also available. `export-messages` writes private chat content to a caller-chosen file with mode 0600; `clear-local --confirm DELETE_LOCAL_DATA` deletes local messages, queue, diagnostics, selected rooms, and sync settings. Use either deliberately. A fresh Android install needs the notification listener grant through `adb shell cmd notification allow_listener dev.kakaoradar.collector/dev.kakaoradar.collector.CollectorService` and an explicit room selection. The existing installation retains its grant and room bindings.

After adding rooms, provision their IDs and existing device credentials with:

```sh
sudo env RADAR_ANDROID_SERIAL=<phone-ip>:<port> python3 server/tools/configure_android_usb.py --install
```

If multiple phones are connected, set `RADAR_ANDROID_SERIAL` for the command. Provisioning adds only explicitly selected rooms and installs the private one-use sync setup without exposing the token in an Intent. `adb reverse tcp:8443 tcp:8443` makes the phone's localhost HTTPS request reach the Pi's loopback listener over Wi-Fi ADB. `radar_adb.py link` restores this mapping; `kakao-radar-adb-maintain@<linux-user>.timer` checks the connection and drains the queue every five minutes. The timer is installed by `install_pi_android_wake.py` with the wake timer.

## Analysis and delivery

The profile helper retains the previously chosen interests, `$1/day` OpenAI cap, Telegram bot, and Seoul 23:00 schedule. Run it only after the credential file has been filled and the phone's selected rooms have been provisioned:

```sh
sudo -u kakaoradar /var/lib/kakao-radar/.state/venv/bin/python server/tools/configure_pi_profile.py
```

The helper configures the database policy for hourly delivery (up to 24 notifications per Seoul calendar day); it does not send a Telegram message. Each enabled room route can produce its own message at a scheduled slot. After the credentials and profile are ready, set `RADAR_ANALYSIS_PROVIDER=openai` and `RADAR_DELIVERY_PROVIDER=telegram` in `/var/lib/kakao-radar/.state/runtime.env`, then enable the requested worker units:

```sh
sudo systemctl enable --now kakao-radar-analysis kakao-radar-delivery kakao-radar-telegram-commands
```

Retention stays disabled because it removes expired data. There is no retention unit in the Pi install; configure a retention window only after reviewing it.

## Optional Xiaomi KakaoTalk wake before delivery

If Xiaomi delays KakaoTalk notifications until the app opens, the optional wake timer checks five minutes before each hourly delivery slot. It opens KakaoTalk only when there are summaries ready to send, waits three seconds, then returns to the home screen. The phone must remain authorized on Wi-Fi ADB. Install the timer after room provisioning:

```sh
sudo python3 server/tools/install_pi_android_wake.py --serial <phone-ip>:<port> --adb-user <linux-user-with-authorized-adb-key>
```

This writes the non-secret ADB/project settings to `/etc/default/kakao-radar-adb`, enables an ADB server instance for the selected Linux user, and enables the connection/upload maintenance and wake timers. The wake timer can bring KakaoTalk briefly to the foreground, then returns to the home screen. To disable both, run `sudo systemctl disable --now kakao-radar-kakao-wake.timer kakao-radar-adb-maintain@<linux-user>.timer kakao-radar-adb@<linux-user>.service`.

## WSL references

`install_wsl_runtime.py`, `install_wsl_local_tls.py`, and `configure_android_usb.py` remain compatibility names for the native Linux tools. Windows-only PowerShell helpers are not used by the Pi deployment. `docs/WSL_RUNTIME.md` describes the prior laptop installation and is historical reference only.
