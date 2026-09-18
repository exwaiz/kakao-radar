"""Project reports onto unseen source evidence and advance only accepted/unknown sends."""
from copy import deepcopy
from hashlib import sha256
from uuid import UUID


def content_hash(text):
    return sha256(text.encode('utf-8')).hexdigest()


def sources(db, device, room, ids):
    return db.execute('''SELECT event_id,text,observed_at,urls FROM messages
        WHERE device_id=%s AND room_id=%s AND event_id=ANY(%s)''',
        (device,room,[UUID(event) for event in ids])).fetchall()


def evidence_ids(payload):
    return list(dict.fromkeys(event for point in payload['points'] for event in point['evidence_ids']))


def project_fresh(db, device, rows):
    progress = {str(row['room_id']):row['observed_through'] for row in
        db.execute('SELECT room_id,observed_through FROM delivery_progress WHERE device_id=%s',(device,)).fetchall()}
    seen = {(str(row['room_id']),str(row['event_id'])) for row in
        db.execute('SELECT room_id,event_id FROM delivery_source_receipts WHERE device_id=%s',(device,)).fetchall()}
    seen_hashes = {(str(row['room_id']),row['content_hash']) for row in
        db.execute('SELECT room_id,content_hash FROM delivery_source_receipts WHERE device_id=%s',(device,)).fetchall()}
    fresh = []
    for row in rows:
        room=str(row['room_id'])
        found={str(source['event_id']):source for source in sources(db,device,row['room_id'],evidence_ids(row['payload']))}
        points=[]
        for point in row['payload']['points']:
            ids=point['evidence_ids']
            # Mixed old/new assertions are omitted rather than rewriting uncited model text.
            if ids and all(event in found and found[event]['observed_at']>progress.get(room,0)
                           and (room,event) not in seen and (room,content_hash(found[event]['text'])) not in seen_hashes
                           for event in ids):
                points.append(point)
        if not points:
            continue
        payload=deepcopy(row['payload'])
        payload['points']=points[:3]
        selected=[found[event] for event in evidence_ids(payload)]
        urls={url for source in selected for url in source['urls']}
        payload['source_urls']=[url for url in payload['source_urls'] if url in urls]
        fresh.append({**row,'payload':payload,'source_from':min(s['observed_at'] for s in selected),
                      'source_through':max(s['observed_at'] for s in selected),
                      'source_hashes':[content_hash(s['text']) for s in selected]})
    return fresh


def windows(db,device,topics,eligible):
    # A successful report consumes its completed analysis interval, including lower-ranked
    # candidates. They must not trickle out as stale "updates" on subsequent slots.
    included={topic['room_id'] for topic in topics}
    ends={room:max(row['source_through'] for row in eligible if str(row['room_id'])==room) for room in included}
    rows=db.execute('''SELECT j.room_id,max(m.observed_at) AS observed_through FROM analysis_items i
        JOIN analysis_jobs j USING(job_id) JOIN messages m ON m.device_id=i.device_id AND m.event_id=i.event_id
        WHERE j.device_id=%s AND j.status='completed' AND j.room_id=ANY(%s) GROUP BY j.room_id''',
        (device,[UUID(room) for room in included])).fetchall()
    for row in rows:
        room=str(row['room_id'])
        ends[room]=max(ends[room],row['observed_through'])
    return ends


def record_delivery(db,device,payload):
    for topic in payload.get('topics',[]):
        room=UUID(topic['room_id'])
        if not db.execute('SELECT 1 FROM rooms WHERE device_id=%s AND room_id=%s AND allowed',(device,room)).fetchone():
            continue
        found=sources(db,device,room,evidence_ids(topic['payload']))
        through=max([source['observed_at'] for source in found]+[payload.get('source_windows',{}).get(str(room),0)])
        if through:
            db.execute('''INSERT INTO delivery_progress(device_id,room_id,observed_through) VALUES(%s,%s,%s)
                ON CONFLICT(device_id,room_id) DO UPDATE SET observed_through=
                GREATEST(delivery_progress.observed_through,excluded.observed_through),updated_at=clock_timestamp()''',
                (device,room,through))
        for source in found:
            db.execute('''INSERT INTO delivery_source_receipts(device_id,room_id,event_id,content_hash)
                VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING''',
                (device,room,source['event_id'],content_hash(source['text'])))
