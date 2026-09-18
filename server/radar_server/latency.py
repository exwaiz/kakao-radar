"""Device-scoped stage latency; channel acceptance is not handset notification display."""
def report(store, device):
    with store.connect() as db:
        upload = db.execute("""WITH delays AS (
            SELECT extract(epoch FROM received_at)-observed_at/1000.0 AS seconds
            FROM messages WHERE device_id=%s AND received_at>clock_timestamp()-interval '7 days')
            SELECT count(*) FILTER(WHERE seconds>=0) AS samples,
              count(*) FILTER(WHERE seconds<0) AS clock_skew_samples,
              percentile_cont(0.5) WITHIN GROUP(ORDER BY seconds) FILTER(WHERE seconds>=0) AS p50_seconds,
              percentile_cont(0.95) WITHIN GROUP(ORDER BY seconds) FILTER(WHERE seconds>=0) AS p95_seconds
            FROM delays""", (device,)).fetchone()
        analysis = db.execute("""WITH delays AS (
            SELECT extract(epoch FROM j.completed_at-min(m.received_at)) AS seconds
            FROM analysis_jobs j JOIN analysis_items i USING(job_id)
              JOIN messages m ON m.device_id=i.device_id AND m.event_id=i.event_id
            WHERE j.device_id=%s AND j.status='completed' AND j.completed_at>clock_timestamp()-interval '7 days'
            GROUP BY j.job_id,j.completed_at)
            SELECT count(*) AS samples, percentile_cont(0.5) WITHIN GROUP(ORDER BY seconds) AS p50_seconds,
              percentile_cont(0.95) WITHIN GROUP(ORDER BY seconds) AS p95_seconds FROM delays""", (device,)).fetchone()
        delivery = db.execute("""SELECT count(*) FILTER(WHERE accepted_at IS NOT NULL) AS accepted,
            count(*) FILTER(WHERE opened_at IS NOT NULL) AS opened,
            percentile_cont(0.95) WITHIN GROUP(ORDER BY extract(epoch FROM accepted_at-created_at))
                FILTER(WHERE accepted_at IS NOT NULL) AS p95_queue_to_accept_seconds,
            percentile_cont(0.95) WITHIN GROUP(ORDER BY extract(epoch FROM opened_at-created_at))
                FILTER(WHERE opened_at IS NOT NULL) AS p95_queue_to_open_seconds
            FROM delivery_outbox WHERE device_id=%s AND created_at>clock_timestamp()-interval '7 days'""", (device,)).fetchone()
    return {'window_days':7, 'capture_to_upload':upload, 'upload_to_analysis':analysis,
            'delivery':delivery, 'handset_notification_display_measured':False}


def mark_opened(store, delivery, device):
    with store.connect() as db:
        db.execute('UPDATE delivery_outbox SET opened_at=COALESCE(opened_at,clock_timestamp()) WHERE delivery_id=%s AND device_id=%s', (delivery,device))
