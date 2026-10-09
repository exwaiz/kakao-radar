package dev.kakaoradar.collector

import android.content.BroadcastReceiver
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.provider.Settings
import android.service.notification.NotificationListenerService
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.security.MessageDigest

/** Shell-only control surface. The manifest requires DUMP, which ordinary apps cannot hold. */
class AdbControlReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != ACTION) return
        val pending = goAsync()
        val app = context.applicationContext as RadarApp
        app.io.execute {
            val reply = try {
                execute(app, intent)
            } catch (_: Exception) {
                failure("command_failed") // Never return exception text containing private data.
            }
            pending.setResultCode(if (reply.optBoolean("ok")) 0 else 1)
            pending.setResultData(reply.toString())
            pending.finish()
        }
    }

    private fun execute(app: RadarApp, intent: Intent): JSONObject = when (intent.getStringExtra("command")) {
        "status" -> status(app)
        "rooms" -> rooms(app)
        "collection-enable" -> {
            if (app.config.bindings.isEmpty()) failure("no_selected_rooms")
            else if (!listenerGranted(app)) failure("notification_access_missing")
            else { app.config.enabled = true; success().put("collection_enabled", true) }
        }
        "collection-disable" -> { app.config.enabled = false; success().put("collection_enabled", false) }
        "room-select" -> selectRoom(app, intent.getStringExtra("candidate_id").orEmpty())
        "room-remove" -> removeRoom(app, intent.getStringExtra("room_id").orEmpty())
        "listener-rebind" -> {
            NotificationListenerService.requestRebind(ComponentName(app, CollectorService::class.java))
            success().put("requested", true)
        }
        "sync-once" -> syncOnce(app)
        "sync-enable" -> synchronized(app.syncLock) {
            app.syncSettings.enabled = true
            if (runCatching { app.syncSettings.snapshot() }.getOrNull() == null) {
                app.syncSettings.enabled = false
                failure("sync_credentials_missing")
            } else {
                SyncScheduler.schedule(app)
                success().put("sync_enabled", true)
            }
        }
        "sync-disable" -> synchronized(app.syncLock) {
            app.syncSettings.enabled = false
            SyncScheduler.cancel(app)
            success().put("sync_enabled", false)
        }
        "sync-reload" -> synchronized(app.syncLock) {
            app.consumeDebugSyncSetup()
            if (app.syncSettings.enabled) success().put("sync_enabled", true)
            else failure("sync_setup_failed")
        }
        "export-diagnostics" -> export(app, false)
        "export-messages" -> export(app, true)
        "clear-local" -> clearLocal(app, intent.getStringExtra("confirm").orEmpty())
        else -> failure("unknown_command")
    }

    private fun status(app: RadarApp): JSONObject {
        val dao = app.db.dao()
        return success()
            .put("version", "3.0.0")
            .put("collection_enabled", app.config.enabled)
            .put("listener_granted", listenerGranted(app))
            .put("listener_connected", app.listenerConnected)
            .put("selected_rooms", app.config.bindings.size)
            .put("discovered_rooms", app.config.candidates().size)
            .put("stored", dao.count())
            .put("pending", dao.queueCount("pending"))
            .put("sent", dao.queueCount("sent"))
            .put("rejected", dao.queueCount("rejected"))
            .put("last_capture_ms", app.config.lastCapture)
            .put("last_listener_connect_ms", app.config.lastConnected)
            .put("sync_enabled", app.syncSettings.enabled)
            .put("last_sync_ms", app.syncSettings.lastSync)
            .put("sync_error", app.syncSettings.error)
            .put("collection_error", app.config.error)
    }

    private fun rooms(app: RadarApp): JSONObject {
        val selected = app.config.bindings
        val local = app.db.dao().roomStatus().associateBy { it.roomId }
        val bindings = JSONArray()
        selected.forEach { room ->
            val counts = local[room.roomId]
            bindings.put(JSONObject().put("room_id", room.roomId).put("title", room.candidate.title)
                .put("candidate_id", candidateId(room.candidate))
                .put("last_capture_ms", room.lastCapture)
                .put("stored", counts?.stored ?: 0).put("pending", counts?.pending ?: 0))
        }
        val candidates = JSONArray()
        app.config.candidates().forEach { candidate ->
            candidates.put(JSONObject().put("candidate_id", candidateId(candidate))
                .put("title", candidate.title)
                .put("selected", selected.any { it.candidate.matches(candidate) }))
        }
        return success().put("selected", bindings).put("discovered", candidates)
    }

    private fun selectRoom(app: RadarApp, id: String): JSONObject {
        val matches = app.config.candidates().filter { candidateId(it) == id }
        if (matches.size != 1) return failure("candidate_not_unique")
        synchronized(app.syncLock) { app.config.select(matches.single()) }
        val room = app.config.bindings.singleOrNull { it.candidate.matches(matches.single()) }
            ?: return failure("selection_failed")
        return success().put("room_id", room.roomId).put("collection_enabled", app.config.enabled)
    }

    private fun removeRoom(app: RadarApp, id: String): JSONObject {
        val matches = app.config.bindings.filter { it.roomId == id || it.roomId.startsWith(id) }
        if (id.length < 8 || matches.size != 1) return failure("room_not_unique")
        synchronized(app.syncLock) { app.config.remove(matches.single().roomId) }
        return success().put("room_id", matches.single().roomId)
            .put("collection_enabled", app.config.enabled)
    }

    private fun syncOnce(app: RadarApp): JSONObject = synchronized(app.syncLock) {
        val target = try { app.syncSettings.snapshot() } catch (_: Exception) {
            app.syncSettings.enabled = false
            app.syncSettings.error = "인증 정보를 다시 설정해 주세요"
            return@synchronized failure("sync_credentials_invalid")
        } ?: return@synchronized failure("sync_disabled")
        val selected = app.config.bindings
        if (selected.isEmpty()) return@synchronized failure("no_selected_rooms")
        val pending = app.db.dao().roomStatus().associate { it.roomId to it.pending }
        val cursor = app.syncSettings.roomCursor.mod(selected.size)
        val index = (0 until selected.size).map { (cursor + it).mod(selected.size) }
            .firstOrNull { (pending[selected[it].roomId] ?: 0) > 0 }
            ?: return@synchronized success().put("outcome", "IDLE")
                .put("pending", app.db.dao().queueCount("pending"))
        val roomId = selected[index].roomId
        val before = app.db.dao().queueCount("pending")
        val selectionVersion = app.config.selectionVersion
        val outcome = SyncEngine(app.db, HttpsUploadTransport(connectTimeoutMs = 5000, readTimeoutMs = 10000))
            .sync(target, roomId) {
                app.syncSettings.current(target) && app.config.selectionVersion == selectionVersion &&
                    app.config.bindings.any { it.roomId == roomId }
            }
        app.syncSettings.roomCursor = (index + 1).mod(selected.size)
        when (outcome) {
            SyncOutcome.SENT -> { app.syncSettings.lastSync = System.currentTimeMillis(); app.syncSettings.error = "" }
            SyncOutcome.RETRY -> app.syncSettings.error = "연결 실패 · 대기열을 유지하고 재시도합니다"
            SyncOutcome.AUTH_REQUIRED -> { app.syncSettings.enabled = false; app.syncSettings.error = "서버 인증을 다시 설정해 주세요" }
            SyncOutcome.PROTOCOL_ERROR -> { app.syncSettings.enabled = false; app.syncSettings.error = "서버 응답 형식 오류 · 대기열을 유지합니다" }
            else -> Unit
        }
        val after = app.db.dao().queueCount("pending")
        val reply = success().put("outcome", outcome.name).put("room_id", roomId)
            .put("processed", before - after).put("pending", after)
        if (outcome in listOf(SyncOutcome.RETRY, SyncOutcome.AUTH_REQUIRED, SyncOutcome.PROTOCOL_ERROR))
            reply.put("ok", false)
        reply
    }

    private fun export(app: RadarApp, messages: Boolean): JSONObject {
        val dir = File(app.filesDir, "exports").apply { mkdirs() }
        val file = File(dir, "radar-${System.currentTimeMillis()}-${if (messages) "messages" else "diagnostics"}.jsonl")
        app.export(file.outputStream(), messages)
        return success().put("path", "files/exports/${file.name}")
    }

    private fun clearLocal(app: RadarApp, confirmation: String): JSONObject {
        if (confirmation != "DELETE_LOCAL_DATA") return failure("confirmation_required")
        synchronized(app.syncLock) {
            app.config.enabled = false
            app.syncSettings.enabled = false
            SyncScheduler.cancel(app)
            app.db.runInTransaction {
                val dao = app.db.dao()
                dao.clearQueue(); dao.clearMessages(); dao.clearSnapshots(); dao.clearDiagnostics(); dao.clearStructures()
            }
            app.config.clear()
            app.syncSettings.clear()
            File(app.filesDir, "exports").deleteRecursively()
        }
        return success().put("cleared", true)
    }

    private fun listenerGranted(context: Context): Boolean =
        Settings.Secure.getString(context.contentResolver, "enabled_notification_listeners")
            .orEmpty().split(':').any {
                ComponentName.unflattenFromString(it)?.packageName == context.packageName
            }

    private fun candidateId(candidate: RoomCandidate): String = MessageDigest.getInstance("SHA-256")
        .digest("${candidate.title}\u0000${candidate.key}\u0000${candidate.shortcut}\u0000${candidate.tag}".toByteArray())
        .take(8).joinToString("") { "%02x".format(it) }

    private fun success() = JSONObject().put("ok", true)
    private fun failure(code: String) = JSONObject().put("ok", false).put("error", code)

    companion object { const val ACTION = "dev.kakaoradar.collector.CONTROL" }
}
