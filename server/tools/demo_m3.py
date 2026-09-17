"""Export a synthetic M3 walkthrough, then delete every fixture from the DB."""
import argparse
import json
import os
from pathlib import Path
import sys
import time
from uuid import uuid4

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from radar_server.app import create_app
from radar_server.providers import ExtractiveProvider
from radar_server.worker import Worker


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output",type=Path,default=Path(".state/m3-demo.json"))
    args = parser.parse_args()
    dsn = os.environ["RADAR_TEST_DATABASE_URL"]
    app = create_app(dsn)
    with TestClient(app) as client:
        store,analysis = app.state.store,app.state.analysis
        device,room,token = uuid4(),uuid4(),"synthetic-demo-"+str(uuid4())
        store.provision(device,room,token)
        headers = {"Authorization":"Bearer "+token}
        try:
            profile = {"enabled":True,"interests":["배포"],"exclude_topics":["광고"],
                       "daily_token_limit":50000,"batch_min_messages":2}
            response = client.put("/v1/profile",headers=headers,json={"expected_version":0,"profile":profile})
            response.raise_for_status()
            now = int(time.time()*1000)
            items = []
            for index,(text,urls) in enumerate([
                ("합성 배포 일정은 내일입니다",["https://example.com/synthetic-release?version=1"]),
                ("정정: 합성 배포 일정이 취소되었습니다",[]),
                ("합성 공연 예약은 다음 주 시작합니다",["https://example.com/synthetic-concert"]),
                ("합성 배포 할인 광고",[]),("ㅋㅋㅋ",[]),
            ]):
                items.append({"event_id":str(uuid4()),"room_id":str(room),"sender_alias":"a"*64,"text":text,
                              "source_time":now-5000+index*1000,"observed_at":now-5000+index*1000,
                              "urls":urls,"quality":"structured","parser_version":2})
            response = client.post("/v1/messages/batch",headers=headers,json={"items":items})
            response.raise_for_status()
            outcome = Worker(analysis,ExtractiveProvider()).process(device,room)
            summaries = client.get(f"/v1/rooms/{room}/summaries",headers=headers).json()["items"]
            report = {"kind":"synthetic_only","fixture_removed_after_export":True,"external_api_calls":0,
                      "outcome":outcome,"summaries":summaries,"analysis":analysis.status(device),
                      "evidence":[client.get(f"/v1/summaries/{s['summary_id']}/evidence",headers=headers).json() for s in summaries]}
            args.output.parent.mkdir(parents=True,exist_ok=True)
            args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str),encoding="utf-8")
            lines = ["# M3 합성 데이터 실행 예시","","외부 API 호출 0회. 추출형 기준선의 결과이며 사용자 품질 평가가 아닙니다.",
                     "실행 후 테스트 DB의 임시 기기와 데이터는 삭제했습니다.","",f"작업 결과: {outcome}",""]
            for summary in summaries:
                topic = summary["payload"]
                lines += [f"## {topic['title']}","",f"관련도 {topic['relevance']} / 후보 {summary['is_candidate']} / {topic['uncertainty']}",""]
                lines += [f"- {point['text']} (근거: {', '.join(point['evidence_ids'])})" for point in topic["points"]]
                lines += ["",topic["notice"],""]
            args.output.with_suffix(".md").write_text("\n".join(lines),encoding="utf-8")
            print(f"Synthetic demo exported: {args.output}")
        finally:
            store.delete_room(device,room)
            with store.connect() as db:
                db.execute("DELETE FROM rooms WHERE device_id=%s",(device,))
                db.execute("DELETE FROM devices WHERE device_id=%s",(device,))


if __name__ == "__main__":
    main()
