"""Internal helper: allow selected rooms for one existing device identity."""
import json
from pathlib import Path
import sys
from uuid import UUID

from pi_paths import DATABASE_URL, SERVER_ROOT
sys.path.insert(0, str(SERVER_ROOT))
from radar_server.store import Store

identity = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
store = Store(DATABASE_URL)
store.migrate()
for room in identity["rooms"]:
    store.provision(UUID(identity["device"]), UUID(room), identity["token"])
print(f"Provisioned {len(identity['rooms'])} selected room(s).")
