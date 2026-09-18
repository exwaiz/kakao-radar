package dev.kakaoradar.collector

import android.app.Application
import android.content.Context
import android.os.Build
import android.util.Base64
import androidx.room.Room
import org.json.JSONArray
import org.json.JSONObject
import java.io.OutputStream
import java.security.SecureRandom
import java.util.UUID
import java.util.concurrent.Executors
import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec

class RadarApp : Application() {
    val io = Executors.newSingleThreadExecutor()
    lateinit var db: RadarDatabase
    lateinit var config: Config
    lateinit var syncSettings: SyncSettings
    val syncLock = Any()
    @Volatile var listenerConnected = false
    private var lastPruned = 0L
    override fun onCreate() {
        super.onCreate()
        config = Config(this)
        syncSettings = SyncSettings(this)
        db = Room.databaseBuilder(this, RadarDatabase::class.java, "radar.db")
            .addMigrations(RadarDatabase.MIGRATION_1_2, RadarDatabase.MIGRATION_2_3).build()
        io.execute { runCatching { prune() }.onFailure { config.error = "저장소 정리 실패" } }
        consumeDebugSyncSetup()
        if (syncSettings.enabled) SyncScheduler.schedule(this)
        // Restore an already granted listener after an app update/process restart.
        runCatching { android.service.notification.NotificationListenerService.requestRebind(
            android.content.ComponentName(this, CollectorService::class.java)) }
    }

    fun prune() {
        val cutoff = System.currentTimeMillis() - 7L * 24 * 60 * 60 * 1000
        db.runInTransaction {
            val expired = db.dao().expiredPending(cutoff)
            if (expired > 0) db.dao().diagnostic(Diagnostic(at = System.currentTimeMillis(), code = "expired_unsent", value = expired))
            db.dao().pruneMessages(cutoff)
            db.dao().pruneSnapshots(cutoff)
            db.dao().pruneDiagnostics(cutoff)
            db.dao().trimDiagnostics()
            db.dao().pruneStructures(System.currentTimeMillis() - 72L * 60 * 60 * 1000)
        }
        lastPruned = System.currentTimeMillis()
    }

    fun pruneIfDue() {
        if (System.currentTimeMillis() - lastPruned > 15 * 60 * 1000) prune()
    }

    fun capture(parsed: ParsedNotification, observedAt: Long) {
        if (!config.enabled) return
        val binding = config.binding ?: return
        if (!binding.matches(parsed.room)) return
        if (binding.shortcut.isBlank() && config.hasTitleCollision(binding)) {
            db.dao().diagnostic(Diagnostic(at = observedAt, code = "room_identity_collision"))
            config.error = "같은 제목의 방이 여러 개입니다 · 대상 방을 다시 확인해 주세요"
            return
        }
        val roomId = config.roomId
        val messages = parsed.messages.map { it.copy(sender = config.alias(it.sender)) }
        // Dedup snapshots contain keyed signatures, never a second copy of message text.
        val signatures = messages.map {
            ObservedMessage("", config.alias(encodeMessages(listOf(it))), it.sourceTime)
        }
        db.runInTransaction {
            val old = db.dao().snapshot(roomId)?.let { decodeMessages(it.payload) }.orEmpty()
            val diff = MessageDiff.compare(old, signatures)
            val quality = if (parsed.method == "standard_extras") "fallback_no_message_time"
                else if (diff.ambiguous) "uncertain_window" else "structured"
            val added = messages.takeLast(diff.added.size)
            val space = (50000 - db.dao().queueCount("pending") - db.dao().queueCount("rejected")).coerceAtLeast(0)
            val retained = added.take(space)
            if (retained.size < added.size) {
                db.dao().diagnostic(Diagnostic(at = observedAt, code = "queue_overflow_entries", value = added.size - retained.size))
                config.error = "전송 대기열 한도 초과 · 일부 알림 항목을 저장하지 못했습니다"
            }
            val saved = retained.map {
                SavedMessage(UUID.randomUUID().toString(), roomId, binding.title, it.sender,
                    it.text, it.sourceTime, observedAt, urls(it.text).toString(), quality)
            }
            db.dao().insertMessages(saved)
            db.dao().enqueue(saved.map { UploadEntry(it.eventId, updatedAt = observedAt) })
            db.dao().saveSnapshot(Snapshot(roomId, encodeMessages(diff.next), observedAt))
            db.dao().diagnostic(Diagnostic(at = observedAt, code = "selected_callbacks"))
            db.dao().diagnostic(Diagnostic(at = observedAt, code = "saved_messages", value = saved.size))
            db.dao().diagnostic(Diagnostic(at = observedAt, code = "suppressed_entries", value = messages.size - diff.added.size))
            if (diff.ambiguous) db.dao().diagnostic(Diagnostic(at = observedAt, code = "uncertain_windows"))
        }
        config.lastCapture = observedAt
        if (db.dao().queueCount("pending") + db.dao().queueCount("rejected") < 50000) config.error = ""
        if (syncSettings.enabled) SyncScheduler.kick(this)
    }

    fun export(output: OutputStream, includeMessages: Boolean = true) {
        prune()
        output.bufferedWriter(Charsets.UTF_8).use { writer ->
            writer.appendLine(JSONObject().put("type", "metadata").put("format_version", 1)
                .put("app_version", "0.3.0").put("device", "${Build.MANUFACTURER} ${Build.MODEL}")
                .put("android", Build.VERSION.RELEASE).put("build", Build.DISPLAY)
                .put("exported_at", System.currentTimeMillis()).put("retention_days", 7)
                .put("includes_messages", includeMessages)
                .put("sender_format", "installation_hmac_sha256").toString())
            var after = 0L
            var afterId = ""
            while (includeMessages) {
                val page = db.dao().page(after, afterId)
                if (page.isEmpty()) break
                page.forEach { m ->
                    writer.appendLine(JSONObject().put("type", "message").put("event_id", m.eventId)
                        .put("room_id", m.roomId).put("room", m.roomTitle).put("sender", m.sender)
                        .put("text", m.text).put("source_time", m.sourceTime ?: JSONObject.NULL)
                        .put("observed_at", m.observedAt).put("urls", JSONArray(m.urlsJson))
                        .put("quality", m.quality).put("parser_version", m.parserVersion).toString())
                }
                after = page.last().observedAt
                afterId = page.last().eventId
            }
            db.dao().diagnostics().forEach { d ->
                writer.appendLine(JSONObject().put("type", "diagnostic").put("at", d.at)
                    .put("code", d.code).put("value", d.value).toString())
            }
            db.dao().structures().forEach { s ->
                writer.appendLine(JSONObject(s.payload).put("type", "notification_structure")
                    .put("at", s.at).put("source", s.source).toString())
            }
        }
    }

    companion object {
        fun encodeMessages(messages: List<ObservedMessage>): String = JSONArray().also { array ->
            messages.forEach { array.put(JSONObject().put("sender", it.sender).put("text", it.text)
                .put("time", it.sourceTime ?: JSONObject.NULL)) }
        }.toString()
        fun decodeMessages(json: String): List<ObservedMessage> {
            val array = JSONArray(json)
            return (0 until array.length()).map { i -> array.getJSONObject(i).let {
                ObservedMessage(it.getString("sender"), it.getString("text"),
                    if (it.isNull("time")) null else it.getLong("time"))
            } }
        }
        fun urls(text: String): JSONArray = JSONArray(Regex("https?://[^\\s<>]+")
            .findAll(text).map { it.value }.distinct().toList())
    }
}

class Config(context: Context) {
    private val prefs = context.getSharedPreferences("collector", Context.MODE_PRIVATE)
    init {
        if (!prefs.contains("alias_key")) {
            val key = ByteArray(32).also { SecureRandom().nextBytes(it) }
            prefs.edit().putString("alias_key", Base64.encodeToString(key, Base64.NO_WRAP)).commit()
        }
    }
    var enabled: Boolean
        get() = prefs.getBoolean("enabled", false)
        set(value) { prefs.edit().putBoolean("enabled", value).commit() }
    var error: String
        get() = prefs.getString("error", "").orEmpty()
        set(value) { prefs.edit().putString("error", value).apply() }
    var lastCapture: Long
        get() = prefs.getLong("last_capture", 0)
        set(value) { prefs.edit().putLong("last_capture", value).apply() }
    var lastConnected: Long
        get() = prefs.getLong("last_connected", 0)
        set(value) { prefs.edit().putLong("last_connected", value).apply() }
    val roomId: String get() = prefs.getString("room_id", "").orEmpty()
    val binding: RoomCandidate? get() = prefs.getString("binding", null)?.let { fromJson(JSONObject(it)) }
    fun select(candidate: RoomCandidate) {
        enabled = false
        val same = binding?.matches(candidate) == true
        prefs.edit().putString("binding", toJson(candidate).toString())
            .putString("room_id", if (same) roomId else UUID.randomUUID().toString()).commit()
    }
    fun discover(candidate: RoomCandidate) {
        val all = candidates().toMutableList()
        if (all.none { it == candidate } || all.count { it.matches(candidate) } > 1) {
            all.removeAll { it.matches(candidate) }
            all.add(0, candidate)
            prefs.edit().putString("candidates", JSONArray(all.take(20).map { toJson(it) }).toString()).apply()
        }
    }
    fun candidates(): List<RoomCandidate> {
        val array = JSONArray(prefs.getString("candidates", "[]"))
        return (0 until array.length()).map { fromJson(array.getJSONObject(it)) }.distinctBy {
            if (it.shortcut.isNotBlank()) "shortcut:${it.shortcut}" else "key:${it.key}:title:${it.title}"
        }
    }
    fun hasTitleCollision(candidate: RoomCandidate): Boolean = candidates().any {
        it.title == candidate.title && !candidate.matches(it)
    }
    fun clear() { prefs.edit().remove("binding").remove("room_id").remove("candidates")
        .remove("last_capture").remove("error").putBoolean("enabled", false).commit() }
    fun alias(sender: String): String {
        if (sender.isEmpty()) return "unknown"
        val mac = Mac.getInstance("HmacSHA256")
        mac.init(SecretKeySpec(Base64.decode(prefs.getString("alias_key", ""), Base64.NO_WRAP), "HmacSHA256"))
        return mac.doFinal(sender.toByteArray(Charsets.UTF_8)).joinToString("") { "%02x".format(it) }
    }
    private fun toJson(c: RoomCandidate) = JSONObject().put("title", c.title).put("key", c.key).put("shortcut", c.shortcut).put("tag", c.tag)
    private fun fromJson(o: JSONObject) = RoomCandidate(o.getString("title"), o.getString("key"), o.getString("shortcut"), o.optString("tag", ""))
}
