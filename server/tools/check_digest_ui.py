"""Temporarily place synthetic HTML text in the --serve fixture for browser QA."""
import argparse
import json
import os
from pathlib import Path
import sys
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from psycopg.types.json import Jsonb
from radar_server.store import Store


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["inject", "restore"])
    args = parser.parse_args()
    state = ROOT/".state"
    report = json.loads((state/"m4-demo.json").read_text(encoding="utf-8"))
    if report.get("synthetic") is not True:
        parser.error("A synthetic M4 demo is required")
    delivery = UUID(report["delivery_id"])
    original = state/"m4-ui-original.json"
    store = Store(os.environ["RADAR_TEST_DATABASE_URL"])
    with store.connect() as db:
        if db.execute("SELECT current_database() AS name").fetchone()["name"] != "radar_m4_test":
            parser.error("Dedicated M4 test database required")
        row = db.execute("SELECT payload FROM delivery_outbox WHERE delivery_id=%s FOR UPDATE",(delivery,)).fetchone()
        if not row:
            parser.error("The --serve fixture is not running")
        if args.action == "inject":
            if original.exists():
                parser.error("Restore the previous fixture first")
            original.write_text(json.dumps(row["payload"],ensure_ascii=False),encoding="utf-8")
            payload = row["payload"]
            payload["topics"][0]["payload"]["title"] = "합성 HTML 문자열 검증"
            payload["topics"][0]["payload"]["points"][0]["text"] = '<img src="invalid-local-test-only" onerror="alert(1)"> 는 대화 속 문자열입니다.'
        else:
            payload = json.loads(original.read_text(encoding="utf-8"))
        db.execute("UPDATE delivery_outbox SET payload=%s WHERE delivery_id=%s",(Jsonb(payload),delivery))
    if args.action == "restore":
        original.unlink()
    print("Synthetic UI fixture " + args.action + " complete")


if __name__ == "__main__":
    main()
