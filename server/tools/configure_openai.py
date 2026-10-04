"""Single-use localhost form for registering an existing OpenAI API key."""
import argparse
import hmac
import os
from pathlib import Path
import secrets
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs
from urllib.request import HTTPSHandler, ProxyHandler, Request, build_opener


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--env-file', required=True)
    parser.add_argument('--port', type=int, default=8767)
    args = parser.parse_args()
    target = Path(args.env_file).resolve()
    if target.is_symlink() or not target.is_file():
        raise SystemExit('Expected an existing private env file')
    nonce = secrets.token_urlsafe(32)
    valid_origins = {f'http://127.0.0.1:{args.port}', f'http://localhost:{args.port}'}
    valid_hosts = {f'127.0.0.1:{args.port}', f'localhost:{args.port}'}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send_page(self, status, markup):
            body = markup.encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Frame-Options', 'DENY')
            self.send_header('Content-Security-Policy', "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'")
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path != '/':
                return self.send_page(404, '<h1>Not found</h1>')
            self.send_page(200, f'''<!doctype html><html lang="ko"><meta charset="utf-8"><title>OpenAI 키 등록</title>
<style>body{{font:17px system-ui;max-width:620px;margin:70px auto;padding:25px;background:#f2f6f8;color:#172b36}}form{{background:white;padding:25px;border-radius:16px}}label{{display:block;margin:20px 0 8px}}input{{box-sizing:border-box;width:100%;padding:12px;font:inherit}}button{{margin-top:25px;padding:12px 20px;font:inherit;background:#1686bd;color:white;border:0;border-radius:8px}}</style>
<h1>OpenAI 키 등록</h1><p>이미 만든 API 키를 입력하세요. 이 Pi에서 인증을 확인한 뒤 전용 자격증명 파일에 저장합니다. 키는 화면이나 로그에 다시 표시하지 않습니다.</p>
<form method="post" action="/save"><input type="hidden" name="nonce" value="{nonce}">
<label for="key">OpenAI API key</label><input id="key" name="key" type="password" autocomplete="off" spellcheck="false" required>
<button>확인 후 저장</button></form></html>''')

        def do_POST(self):
            if (self.path != '/save'
                    or self.headers.get('Origin') not in valid_origins
                    or self.headers.get('Host') not in valid_hosts):
                return self.send_page(403, '<h1>잘못된 요청입니다.</h1>')
            try:
                length = int(self.headers.get('Content-Length', '0'))
            except ValueError:
                length = 0
            if not 0 < length <= 4096:
                return self.send_page(400, '<h1>입력 형식을 확인하세요.</h1><a href="/">다시 입력</a>')
            try:
                fields = parse_qs(self.rfile.read(length).decode('utf-8'))
            except (UnicodeDecodeError, ValueError):
                fields = {}
            if not hmac.compare_digest(fields.get('nonce', [''])[0], nonce):
                return self.send_page(403, '<h1>요청이 만료됐습니다.</h1>')
            key = fields.get('key', [''])[0].strip()
            if not key or any(c.isspace() for c in key):
                return self.send_page(400, '<h1>키 형식을 확인하세요.</h1><a href="/">다시 입력</a>')
            request = Request('https://api.openai.com/v1/models', headers={
                'Authorization': 'Bearer ' + key,
                'Accept': 'application/json',
                'User-Agent': 'kakao-radar-credential-setup',
            })
            try:
                opener = build_opener(ProxyHandler({}), HTTPSHandler())
                with opener.open(request, timeout=20) as response:
                    if response.status != 200:
                        raise ValueError('unauthorized')
                    response.read(1)
            except HTTPError as error:
                if error.code in (401, 403):
                    print('OpenAI setup: key rejected by API', flush=True)
                    return self.send_page(400, '<h1>키 인증에 실패했습니다.</h1><p>키와 프로젝트 접근 권한을 확인한 뒤 다시 입력하세요.</p><a href="/">다시 입력</a>')
                print('OpenAI setup: API returned an error', flush=True)
                return self.send_page(502, '<h1>OpenAI API 확인에 실패했습니다.</h1><p>잠시 후 다시 시도하세요.</p><a href="/">다시 입력</a>')
            except (URLError, TimeoutError, OSError):
                print('OpenAI setup: network connection failed', flush=True)
                return self.send_page(502, '<h1>OpenAI API에 연결하지 못했습니다.</h1><p>네트워크를 확인한 뒤 다시 시도하세요.</p><a href="/">다시 입력</a>')
            except ValueError:
                return self.send_page(400, '<h1>키 인증에 실패했습니다.</h1><a href="/">다시 입력</a>')

            try:
                lines = target.read_text(encoding='utf-8').splitlines()
                lines = [line for line in lines if not line.startswith('OPENAI_API_KEY=')]
                lines.append('OPENAI_API_KEY=' + key)
                content = ('\n'.join(lines) + '\n').encode('utf-8')
                old_stat = target.stat()
                fd, temp_name = tempfile.mkstemp(prefix='.credentials-', dir=str(target.parent))
                try:
                    os.fchmod(fd, old_stat.st_mode & 0o777)
                    with os.fdopen(fd, 'wb') as temp:
                        temp.write(content)
                        temp.flush()
                        os.fsync(temp.fileno())
                    os.chown(temp_name, old_stat.st_uid, old_stat.st_gid)
                    os.replace(temp_name, target)
                finally:
                    if os.path.exists(temp_name):
                        os.unlink(temp_name)
            except Exception:
                print('OpenAI setup: private file save failed', flush=True)
                return self.send_page(500, '<h1>키를 안전하게 저장하지 못했습니다.</h1><p>관리자에게 알리세요. 키는 저장되지 않았습니다.</p>')
            self.send_page(200, '<h1>OpenAI 키를 확인하고 저장했습니다.</h1><p>이제 이 화면을 닫아도 됩니다.</p>')
            print('OpenAI credentials configured', flush=True)
            threading.Thread(target=self.server.shutdown, daemon=True).start()

    with HTTPServer(('127.0.0.1', args.port), Handler) as server:
        print('OpenAI setup form ready on localhost', flush=True)
        server.serve_forever()


if __name__ == '__main__':
    main()
