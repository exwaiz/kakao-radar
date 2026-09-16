package dev.kakaoradar.collector

import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification

class CollectorService : NotificationListenerService() {
    private val app get() = application as RadarApp
    override fun onListenerConnected() {
        app.listenerConnected = true
        app.config.lastConnected = System.currentTimeMillis()
        // Existing notifications provide room discovery only, not historical capture.
        runCatching { activeNotifications?.forEach { inspect(it, false) } }
            .onFailure { app.config.error = "현재 알림 조회 실패 · 새 알림을 기다려 주세요" }
    }
    override fun onListenerDisconnected() { app.listenerConnected = false }
    override fun onDestroy() { app.listenerConnected = false; super.onDestroy() }
    override fun onNotificationPosted(sbn: StatusBarNotification) { inspect(sbn, true) }

    private fun inspect(sbn: StatusBarNotification, capture: Boolean) {
        if (sbn.packageName != NotificationParser.PACKAGE) return
        val at = System.currentTimeMillis()
        // Freeze the capture decision at arrival, and recheck on the serial store thread.
        val enabledAtArrival = app.config.enabled
        val roomAtArrival = app.config.roomId
        app.io.execute {
            try {
                val parsed = NotificationParser.parse(sbn)
                if (parsed == null) {
                    app.db.dao().diagnostic(Diagnostic(at = at, code = "unsupported_kakao_callbacks"))
                } else {
                    app.config.discover(parsed.room)
                    if (capture && enabledAtArrival && roomAtArrival == app.config.roomId) app.capture(parsed, at)
                }
                app.pruneIfDue()
            } catch (_: Exception) {
                // Never log notification payloads or exception messages containing chat content.
                app.config.error = "수집 처리 실패 · 저장 공간과 권한을 확인해 주세요"
            }
        }
    }
}
