import os
import time
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from radar_server.app import create_app


@pytest.fixture
def setup():
    dsn=os.environ.get("RADAR_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("Set RADAR_TEST_DATABASE_URL to a disposable PostgreSQL database")
    app=create_app(dsn)
    with TestClient(app) as client:
        store=app.state.store
        device,room,token=uuid4(),uuid4(),"fixture-secret-"+str(uuid4())
        store.provision(device,room,token)
        try:
            yield client,store,device,room,{"Authorization":"Bearer "+token}
        finally:
            with store.connect() as db:
                db.execute("DELETE FROM receipts WHERE device_id=%s",(device,))
                db.execute("DELETE FROM rooms WHERE device_id=%s",(device,))
                db.execute("DELETE FROM devices WHERE device_id=%s",(device,))


def message(room,**changes):
    return {"event_id":str(uuid4()),"room_id":str(room),"sender_alias":"a"*64,
            "text":"synthetic fixture https://example.com","source_time":12345,
            "observed_at":int(time.time()*1000),"urls":["https://example.com"],
            "quality":"structured","parser_version":2,**changes}


def send(client,headers,items):
    response=client.post("/v1/messages/batch",headers=headers,json={"items":items})
    assert response.status_code==200,response.text
    return response.json()["results"]


def test_authenticated_and_idempotent_after_lost_response(setup):
    client,store,device,room,headers=setup
    item=message(room)
    assert client.post("/v1/messages/batch",json={"items":[item]}).status_code==401
    assert send(client,headers,[item])[0]["status"]=="accepted"
    # Pretend the first response never reached the device; ID is reused.
    assert send(client,headers,[item])[0]["status"]=="duplicate"
    assert client.get("/v1/status",headers=headers).json()["stored_messages"]==1


def test_conflicting_event_id_does_not_overwrite(setup):
    client,store,device,room,headers=setup
    item=message(room)
    send(client,headers,[item])
    result=send(client,headers,[{**item,"text":"different fixture"}])[0]
    assert result["status"]=="rejected" and result["reason"]=="event_id_conflict"
    with store.connect() as db:
        assert db.execute("SELECT text FROM messages WHERE device_id=%s",(device,)).fetchone()["text"]==item["text"]


def test_partial_rejection_and_forbidden_room(setup):
    client,store,device,room,headers=setup
    items=[message(room),message(uuid4()),message(room,text=""),message(room,sender_alias="raw-nickname-fixture")]
    results=send(client,headers,items)
    assert [r["status"] for r in results]==["accepted","rejected","rejected","rejected"]
    assert client.get("/v1/status",headers=headers).json()["stored_messages"]==1
    assert "raw-nickname-fixture" not in str(results)


def test_concurrent_retries_store_once(setup):
    client,store,device,room,headers=setup
    item=message(room)
    with ThreadPoolExecutor(max_workers=4) as workers:
        statuses=list(workers.map(lambda _:send(client,headers,[item])[0]["status"],range(8)))
    assert statuses.count("accepted")==1 and statuses.count("duplicate")==7
    assert store.status(device)["stored_messages"]==1


def test_database_failure_rolls_back_batch(setup):
    client,store,device,room,headers=setup
    # Fixture-only constraint causes a real PostgreSQL transaction failure halfway through.
    constraint="fixture_"+uuid4().hex
    with store.connect() as db:
        db.execute(f"ALTER TABLE messages ADD CONSTRAINT {constraint} CHECK (text != 'force-rollback-fixture')")
    try:
        response=client.post("/v1/messages/batch",headers=headers,json={"items":[message(room),message(room,text="force-rollback-fixture")]})
        assert response.status_code==503
        assert "force-rollback-fixture" not in response.text
        assert store.status(device)["stored_messages"]==0
        with store.connect() as db:
            assert db.execute("SELECT count(*) AS n FROM receipts WHERE device_id=%s",(device,)).fetchone()["n"]==0
    finally:
        with store.connect() as db: db.execute(f"ALTER TABLE messages DROP CONSTRAINT {constraint}")


def test_device_revocation(setup):
    client,store,device,room,headers=setup
    with store.connect() as db: db.execute("UPDATE devices SET active=false WHERE device_id=%s",(device,))
    assert client.post("/v1/messages/batch",headers=headers,json={"items":[message(room)]}).status_code==401


def test_delete_revokes_room_and_queued_retries_cannot_restore(setup):
    client,store,device,room,headers=setup
    item=message(room)
    send(client,headers,[item])
    result=client.delete(f"/v1/rooms/{room}/data",headers=headers)
    assert result.json()["deleted_events"]==1
    assert send(client,headers,[item])[0]["reason"]=="room_not_allowed"
    assert store.status(device)["stored_messages"]==0


def test_expired_messages_are_not_resurrected(setup):
    client,store,device,room,headers=setup
    item=message(room,observed_at=int(time.time()*1000)-8*86400000)
    assert send(client,headers,[item])[0]["reason"]=="expired"
    assert store.status(device)["stored_messages"]==0


def test_retention_preserves_retry_receipt(setup):
    client,store,device,room,headers=setup
    item=message(room)
    send(client,headers,[item])
    with store.connect() as db:
        db.execute("UPDATE messages SET observed_at=%s WHERE device_id=%s",(int(time.time()*1000)-8*86400000,device))
    store.prune()
    assert store.status(device)["stored_messages"]==0
    assert send(client,headers,[item])[0]["status"]=="duplicate"
    assert store.status(device)["stored_messages"]==0


def test_body_and_item_limits_and_safe_validation(setup):
    client,store,device,room,headers=setup
    assert client.post("/v1/messages/batch",headers=headers,json={"items":[message(room) for _ in range(101)]}).status_code==422
    assert client.post("/v1/messages/batch",headers=headers,content=b"x"*(1024*1024+1)).status_code==413
    fixture="secret-invalid-fixture"
    response=client.post("/v1/messages/batch",headers=headers,json={"items":[message(room,event_id=fixture)]})
    assert response.status_code==422 and fixture not in response.text


def test_other_device_status_and_deletion_are_scoped(setup):
    client,store,device,room,headers=setup
    other,token=uuid4(),"fixture-"+str(uuid4())
    store.provision(other,room,token)
    try:
        send(client,headers,[message(room)])
        other_headers={"Authorization":"Bearer "+token}
        assert client.get("/v1/status",headers=other_headers).json()["stored_messages"]==0
        assert client.delete(f"/v1/rooms/{room}/data",headers=other_headers).json()["deleted_events"]==0
        assert store.status(device)["stored_messages"]==1
    finally:
        with store.connect() as db:
            db.execute("DELETE FROM rooms WHERE device_id=%s",(other,))
            db.execute("DELETE FROM devices WHERE device_id=%s",(other,))
