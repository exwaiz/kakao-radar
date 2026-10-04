# Raspberry Pi runtime

This runbook replaces the laptop-specific WSL/Windows deployment. It targets Raspberry Pi OS/Debian 13 on 64-bit ARM. PostgreSQL and the API run on the Pi; the only phone path is Android USB debugging with `adb reverse`. The API binds to `127.0.0.1:8000`, and its local HTTPS endpoint binds to `127.0.0.1:8443`. No router or firewall port is opened.

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

Authorize this Pi once over USB, then use Android Wireless debugging pairing (or `adb tcpip` on older devices). Keep the Pi and phone on a network that permits device-to-device traffic and check that `adb devices -l` shows the Wi-Fi transport as `device`. Set `RADAR_ANDROID_SERIAL` to that Wi-Fi serial when USB and Wi-Fi transports are both present. Select the intended KakaoTalk rooms in the app first. Build or copy the debug APK to `android/app/build/outputs/apk/debug/app-debug.apk`, then run:

```sh
sudo env RADAR_ANDROID_SERIAL=<phone-ip>:<port> python3 server/tools/configure_android_usb.py --install
```

If multiple phones are connected, set `RADAR_ANDROID_SERIAL` for the command. Provisioning adds only the rooms selected in the app. `adb install -r` updates the APK while preserving its app data; the tool does not clear app storage. `adb reverse tcp:8443 tcp:8443` makes the phone's localhost HTTPS request reach the Pi's loopback listener over the selected ADB transport, including Wi-Fi.

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

If Xiaomi delays KakaoTalk notifications until the app opens, the optional wake timer checks five minutes before each hourly delivery slot. It opens KakaoTalk only when there are summaries ready to send, waits three seconds, then returns to Kakao Radar. The phone must remain authorized on Wi-Fi ADB. Install the timer after room provisioning:

```sh
sudo python3 server/tools/install_pi_android_wake.py --serial <phone-ip>:<port> --adb-user <linux-user-with-authorized-adb-key>
```

This writes the non-secret ADB/project settings to `/etc/default/kakao-radar-adb`, enables an ADB server instance for the selected Linux user, and enables the wake timer. The timer can bring KakaoTalk briefly to the foreground; verify that this fits the phone's use. To disable it, run `sudo systemctl disable --now kakao-radar-kakao-wake.timer kakao-radar-adb@<linux-user>.service`.

## WSL references

`install_wsl_runtime.py`, `install_wsl_local_tls.py`, and `configure_android_usb.py` remain compatibility names for the native Linux tools. Windows-only PowerShell helpers are not used by the Pi deployment. `docs/WSL_RUNTIME.md` describes the prior laptop installation and is historical reference only.
