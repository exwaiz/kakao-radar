"""Load only the credentials needed by each component from the approved private file."""
import argparse
import os
from pathlib import Path
import runpy
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

parser = argparse.ArgumentParser()
parser.add_argument('component', choices=['api','analysis','delivery','retention'])
parser.add_argument('--private-env', required=True)
parser.add_argument('--port', default='8000')
parser.add_argument('--ssl-certfile')
parser.add_argument('--ssl-keyfile')
args = parser.parse_args()
names = {'analysis': {'OPENAI_API_KEY'}, 'delivery': {'RADAR_TELEGRAM_BOT_TOKEN','RADAR_TELEGRAM_CHAT_ID'}}.get(args.component,set())
for line in Path(args.private_env).read_text(encoding='utf-8').splitlines():
    key, separator, value = line.partition('=')
    if separator and key in names:
        os.environ[key] = value.strip().strip('"').strip("'")
modules = {'analysis':'radar_server.worker','delivery':'radar_server.delivery_worker','retention':'radar_server.retention'}
if args.component == 'api':
    sys.argv = ['uvicorn','radar_server.app:create_app','--factory','--host','127.0.0.1','--port',args.port,'--no-access-log','--log-level','warning']
    if args.ssl_certfile and args.ssl_keyfile:
        sys.argv += ['--ssl-certfile',args.ssl_certfile,'--ssl-keyfile',args.ssl_keyfile]
    runpy.run_module('uvicorn',run_name='__main__')
else:
    sys.argv = [modules[args.component]]
    runpy.run_module(modules[args.component],run_name='__main__')
