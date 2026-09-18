"""Single-use localhost credential form. Never prints tokens or Telegram responses."""
import argparse
import hmac
import json
import os
from pathlib import Path
import secrets
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs

import httpx


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--env-file', required=True)
    parser.add_argument('--port', type=int, default=8767)
    args = parser.parse_args()
    target = Path(args.env_file).resolve()
    if target.is_symlink() or not target.is_file():
        raise SystemExit('Expected an existing private env file')
    nonce = secrets.token_urlsafe(32)
    origin = f'http://127.0.0.1:{args.port}'
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def send(self, status, text):
            body = text.encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Frame-Options', 'DENY')
            self.send_header('Content-Security-Policy', "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'")
            self.send_header('Content-Length', str(len(body)))
            self.end_headers(); self.wfile.write(body)
        def do_GET(self):
            if self.path != '/': return self.send(404, 'Not found')
            self.send(200, f'''<!doctype html><html lang="ko"><meta charset="utf-8"><title>Telegram 봇 연결</title>
<style>body{{font:17px system-ui;max-width:620px;margin:70px auto;padding:25px;background:#f2f6f8;color:#172b36}}form{{background:white;padding:25px;border-radius:16px}}label{{display:block;margin:20px 0 8px}}input{{box-sizing:border-box;width:100%;padding:12px;font:inherit}}button{{margin-top:25px;padding:12px 20px;font:inherit;background:#1686bd;color:white;border:0;border-radius:8px}}</style>
<h1>Telegram 봇 연결</h1><p>기존 봇의 토큰과 본인 개인 채팅 ID를 입력하세요. 토큰은 이 노트북에만 저장하며 채팅이나 GitHub에 표시하지 않습니다.</p>
<form method="post" action="/save"><input type="hidden" name="nonce" value="{nonce}">
<label for="token">BotFather에서 받은 봇 토큰</label><input id="token" name="token" type="password" autocomplete="off" required>
<label for="chat">본인 개인 chat ID</label><input id="chat" name="chat" inputmode="numeric" autocomplete="off" required pattern="[0-9]+">
<p>Telegram에서 먼저 해당 봇에 /start를 보내주세요. 개인 채팅만 연결됩니다.</p><button>연결 확인 후 저장</button></form></html>''')
        def do_POST(self):
            if self.path != '/save' or self.headers.get('Origin') != origin:
                return self.send(403, 'Invalid request')
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 4096: return self.send(400, 'Invalid request')
            fields = parse_qs(self.rfile.read(length).decode('utf-8'))
            if not hmac.compare_digest(fields.get('nonce',[''])[0], nonce): return self.send(403, 'Invalid request')
            token, chat = fields.get('token',[''])[0].strip(), fields.get('chat',[''])[0].strip()
            stage = '입력 형식'
            try:
                from radar_server.telegram_channel import TelegramChannel
                TelegramChannel(token, chat)
                with httpx.Client(timeout=15, trust_env=False) as client:
                    base = f'https://api.telegram.org/bot{token}'
                    stage = '봇 토큰 인증'
                    me = client.post(base+'/getMe').json()
                    if me.get('ok') is not True:
                        raise ValueError()
                    stage = '개인 채팅 확인 (/start 및 chat ID)'
                    room = client.post(base+'/getChat',json={'chat_id':chat}).json()
                if me.get('ok') is not True or room.get('ok') is not True or room['result'].get('type') != 'private' or str(room['result'].get('id')) != chat:
                    raise ValueError()
                stage = '로컬 비밀 파일 저장'
                lines = target.read_text(encoding='utf-8').splitlines()
                names = ('RADAR_TELEGRAM_BOT_TOKEN=', 'RADAR_TELEGRAM_CHAT_ID=')
                lines = [line for line in lines if not line.startswith(names)]
                lines.extend([names[0]+token,names[1]+chat])
                target.write_text('\n'.join(lines)+'\n',encoding='utf-8')
            except httpx.HTTPError:
                print('Telegram setup: network connection failed', flush=True)
                return self.send(400, '<h1>Telegram 서버 연결에 실패했습니다.</h1><p>입력값 오류로 판단하지 않았습니다. 노트북의 네트워크 연결을 확인한 후 다시 시도하세요.</p><a href="/">다시 입력</a>')
            except Exception:
                print('Telegram setup failed at: ' + stage, flush=True)
                return self.send(400, '<h1>연결을 확인하지 못했습니다.</h1><p>실패 단계: ' + stage + '</p><p>봇을 열어 /start를 보내고 본인 개인 chat ID를 확인하세요.</p><a href="/">다시 입력</a>')
            self.send(200, '<h1>Telegram 연결 정보를 저장했습니다.</h1><p>이제 이 화면을 닫아도 됩니다.</p>')
            print('Telegram credentials configured', flush=True)
            threading.Thread(target=self.server.shutdown, daemon=True).start()
    with HTTPServer(('127.0.0.1',args.port),Handler) as server:
        print('Telegram setup form ready on localhost', flush=True)
        server.serve_forever()


if __name__ == '__main__':
    main()
