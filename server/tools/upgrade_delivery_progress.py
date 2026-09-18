"""Local maintenance after stopping delivery: seed progress and discard legacy queues."""
import argparse
import os
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from radar_server.store import Store
from radar_server.delivery_store import DeliveryStore

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    store=Store(os.environ['RADAR_DATABASE_URL'])
    store.migrate()
    with store.connect() as db:
        devices=db.execute('SELECT device_id FROM devices ORDER BY device_id FOR UPDATE').fetchall()
        cancelled=0
        for device in devices:
            rows=db.execute("SELECT delivery_id FROM delivery_outbox WHERE device_id=%s AND status IN ('pending','retry_wait') AND NOT payload ? 'source_windows' FOR UPDATE",(device['device_id'],)).fetchall()
            for row in rows:
                DeliveryStore._cancel(db,row['delivery_id'],'delivery_progress_upgrade')
                cancelled+=1
        rooms=db.execute('SELECT count(*) AS n FROM delivery_progress').fetchone()['n']
    print({'seeded_rooms':rooms,'cancelled_legacy_queues':cancelled})

if __name__=='__main__':
    main()
