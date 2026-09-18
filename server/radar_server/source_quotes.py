"""Quote only scoped, live source text. No model rewriting and no persistent quote copies."""
from uuid import UUID

def attach_quotes(db, device, payload):
    for topic in payload.get('topics',[]):
        summary = topic['payload']
        ids = list(dict.fromkeys(event for point in summary['points'] for event in point['evidence_ids']))
        found = db.execute('SELECT event_id,text,observed_at FROM messages WHERE device_id=%s AND room_id=%s AND event_id=ANY(%s)',
            (device,UUID(topic['room_id']),[UUID(event) for event in ids])).fetchall()
        sources = {str(row['event_id']):row for row in found}
        quotes = []
        for event in ids:
            source = sources.get(event)
            text = source['text'] if source else ''
            if not text.strip():
                continue
            snippet = text[:80]
            quotes.append({'evidence_id':event,'text':snippet,'truncated':len(text)>len(snippet),'observed_at':source['observed_at']})
            if len(quotes)==2:
                break
        summary['quotes']=quotes
