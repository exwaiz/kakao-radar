import os
import time
from .store import Store

store=Store(os.environ["RADAR_DATABASE_URL"])
store.migrate()
while True:
    try:
        print(store.prune(),flush=True)
    except Exception:
        print("Retention temporarily unavailable",flush=True)
    time.sleep(3600)
