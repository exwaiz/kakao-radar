"""Synthetic M2 -> M3 -> M4 demonstration. Uses a mocked ntfy endpoint only."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import httpx
from fastapi.testclient import TestClient

from radar_server.app import create_app
from radar_server.delivery_channels import DigestLinks, NtfyChannel
from radar_server.delivery_worker import DeliveryWorker
from radar_server.providers import ExtractiveProvider
from radar_server.worker import Worker


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--port", type=int, default=8004)
    args = parser.parse_args()
    dsn = os.environ["RADAR_TEST_DATABASE_URL"]
    secret = "synthetic-demo-" + uuid4().hex
    links = DigestLinks("https://radar.example.com", secret)
    app = create_app(dsn, digest_links=links)
    device, room, token = uuid4(), uuid4(), "synthetic-demo-" + uuid4().hex
    store, analysis, delivery = app.state.store, app.state.analysis, app.state.delivery
    headers = {"Authorization": "Bearer " + token}
    server = None
    try:
        with TestClient(app) as client:
            store.provision(device, room, token)
            response = client.put("/v1/profile",headers=headers,json={"expected_version":0,"profile":{
                "enabled":True,"interests":["배포"],"daily_token_limit":1000000}})
            assert response.status_code == 200
            response = client.put("/v1/delivery/policy",headers=headers,json={"expected_version":0,"policy":{
                "enabled":True,"daily_times":["09:00","18:00"],"daily_notification_limit":2}})
            assert response.status_code == 200
            texts = ["합성 배포 일정은 다음 주입니다. https://example.com/synthetic/deploy",
                     "합성 배포 일정은 취소됐습니다. https://example.com/synthetic/deploy",
                     "합성 배포 도구의 새 문서입니다. https://example.com/synthetic/tool"]
            now = int(time.time()*1000)
            messages = [{"event_id":str(uuid4()),"room_id":str(room),"sender_alias":"a"*64,"text":text,
                "source_time":now+index,"observed_at":now+index,"urls":[text.split()[-1]],"quality":"structured","parser_version":2}
                for index,text in enumerate(texts)]
            assert client.post("/v1/messages/batch",headers=headers,json={"items":messages}).status_code == 200
            assert Worker(analysis,ExtractiveProvider()).process(device,room,force=True) == "completed"
            with store.connect() as db:
                db.execute("UPDATE delivery_settings SET next_due_at=now()-interval '1 minute' WHERE device_id=%s",(device,))
            published = []
            def receive(request):
                published.append(json.loads(request.content))
                return httpx.Response(200,json={"id":"syntheticDemo1","event":"message","topic":"synthetic-topic"})
            channel = NtfyChannel("https://ntfy.example.com","synthetic-topic","synthetic-private-token",links,httpx.MockTransport(receive))
            worker = DeliveryWorker(delivery,channel)
            assert worker.process(device) == "accepted" and len(published) == 1
            row = delivery.history(device)[0]
            identifier = row["delivery_id"]
            scoped = {"Authorization":"Digest "+links.token(identifier)}
            digest = client.get(f"/v1/digests/{identifier}",headers=scoped).json()
            first = digest["topics"][0]["summary_id"]
            response = client.put(f"/v1/digests/{identifier}/summaries/{first}/feedback",headers=scoped,json={"rating":"useful"})
            assert response.status_code == 200
            with store.connect() as db:
                db.execute("UPDATE delivery_settings SET next_due_at=now()-interval '1 minute' WHERE device_id=%s",(device,))
            assert worker.process(device) == "idle" and len(published) == 1
            report = {"synthetic":True,"external_network_calls":0,"raw_messages":len(messages),
                      "topics":len(digest["topics"]),"delivery_status":"accepted","mock_ntfy_calls":len(published),
                      "feedback":"useful","repeat_calls":0,"evidence_available":all(e["availability"]=="available" for t in digest["topics"] for e in t["evidence"]),
                      "phone_receipt":"not_tested","delivery_id":str(identifier),"notification":published[0]}
            state = ROOT / ".state"
            state.mkdir(exist_ok=True)
            (state/"m4-demo.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
            (state/"m4-demo.md").write_text("# M4 합성 실행\n\n"
                f"합성 메시지 {len(messages)}건 → M3 관심 주제 {len(digest['topics'])}개 → 모의 ntfy 수락 1회.\n\n"
                "근거 원문 조회와 유용함 피드백 저장을 확인했습니다. 동일 요약을 다시 발송하지 않았습니다.\n\n"
                "외부 네트워크 호출 0회. 실제 본폰 수신·알림량·유용성 평가는 대기입니다.\n",encoding="utf-8")
            print(json.dumps({k:v for k,v in report.items() if k!="notification"},ensure_ascii=False),flush=True)
        if args.serve:
            env = dict(os.environ,RADAR_DATABASE_URL=dsn,RADAR_PUBLIC_URL="https://radar.example.com",RADAR_DIGEST_LINK_SECRET=secret)
            server = subprocess.Popen([sys.executable,"-m","uvicorn","radar_server.app:create_app","--factory",
                "--host","127.0.0.1","--port",str(args.port),"--no-access-log"],cwd=ROOT,env=env,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name=="nt" else 0)
            print(f"Synthetic UI: http://127.0.0.1:{args.port}/digest/{identifier}#key={links.token(identifier)}",flush=True)
            stop_file = ROOT/".state"/"stop-m4-ui"
            if stop_file.exists():
                stop_file.unlink()
            while server.poll() is None and not stop_file.exists():
                time.sleep(0.5)
    finally:
        if server and server.poll() is None:
            server.terminate()
            server.wait(timeout=15)
        with store.connect() as db:
            db.execute("DELETE FROM receipts WHERE device_id=%s",(device,))
            db.execute("DELETE FROM rooms WHERE device_id=%s",(device,))
            db.execute("DELETE FROM devices WHERE device_id=%s",(device,))


if __name__ == "__main__":
    main()
