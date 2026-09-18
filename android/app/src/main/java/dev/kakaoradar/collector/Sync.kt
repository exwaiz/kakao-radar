package dev.kakaoradar.collector

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import androidx.work.*
import org.json.JSONArray
import org.json.JSONObject
import java.net.URL
import java.io.ByteArrayOutputStream
import java.security.KeyStore
import java.util.UUID
import java.util.concurrent.TimeUnit
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec
import javax.net.ssl.HttpsURLConnection
import javax.net.ssl.SSLSocketFactory
import javax.net.ssl.SSLContext
import javax.net.ssl.TrustManagerFactory
import java.security.cert.CertificateFactory
import android.content.pm.ApplicationInfo

data class SyncTarget(val server: String, val device: String, val room: String, val token: String, val generation: String, val localCa: String = "")

class SyncSettings(private val context: Context, private val preferenceName: String = "sync", private val keyAlias: String = "radar-sync-token") {
    private val prefs = context.getSharedPreferences(preferenceName, Context.MODE_PRIVATE)
    var enabled: Boolean
        get() = prefs.getBoolean("enabled", false)
        set(value) { prefs.edit().putBoolean("enabled", value).putString("generation", UUID.randomUUID().toString()).commit() }
    var lastSync: Long
        get() = prefs.getLong("last_sync", 0)
        set(value) { prefs.edit().putLong("last_sync", value).apply() }
    var error: String
        get() = prefs.getString("error", "").orEmpty()
        set(value) { prefs.edit().putString("error", value).apply() }
    val server get() = prefs.getString("server", "").orEmpty()
    val device get() = prefs.getString("device", "").orEmpty()
    val room get() = prefs.getString("room", "").orEmpty()
    fun configure(server: String, device: String, room: String, token: String, localCa: String = "") {
        val url = URL(server)
        require(url.protocol == "https" && url.host.isNotBlank() && url.userInfo == null && url.query == null && url.ref == null && url.path in listOf("", "/"))
        UUID.fromString(device); UUID.fromString(room)
        require(token.length in 32..512 && token.all { it.code in 33..126 })
        if (localCa.isNotBlank()) {
            require(context.applicationInfo.flags and ApplicationInfo.FLAG_DEBUGGABLE != 0)
            require(url.host == "localhost" && url.port == 8443 && localCa.length <= 16384)
            CertificateFactory.getInstance("X.509").generateCertificate(localCa.byteInputStream())
        }
        val cipher = Cipher.getInstance("AES/GCM/NoPadding").apply { init(Cipher.ENCRYPT_MODE, secretKey()) }
        val encrypted = Base64.encodeToString(cipher.iv + cipher.doFinal(token.toByteArray(Charsets.UTF_8)), Base64.NO_WRAP)
        prefs.edit().putString("server", server.trimEnd('/')).putString("device", device).putString("room", room)
            .putString("token_encrypted", encrypted).putString("local_ca", localCa).putBoolean("enabled", true)
            .putString("generation", UUID.randomUUID().toString()).putString("error", "").commit()
    }
    private fun secretKey(): SecretKey {
        val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (store.getKey(keyAlias, null) as? SecretKey)?.let { return it }
        return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore").apply {
            init(KeyGenParameterSpec.Builder(keyAlias, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build())
        }.generateKey()
    }
    fun snapshot(): SyncTarget? {
        if (!enabled) return null
        val encoded = prefs.getString("token_encrypted", null) ?: return null
        val bytes = Base64.decode(encoded, Base64.NO_WRAP)
        val cipher = Cipher.getInstance("AES/GCM/NoPadding").apply {
            init(Cipher.DECRYPT_MODE, secretKey(), GCMParameterSpec(128, bytes.copyOfRange(0, 12)))
        }
        val token = String(cipher.doFinal(bytes.copyOfRange(12, bytes.size)), Charsets.UTF_8)
        return SyncTarget(server, device, room, token, prefs.getString("generation", "").orEmpty(), prefs.getString("local_ca", "").orEmpty())
    }
    fun current(target: SyncTarget) = enabled && prefs.getString("generation", "") == target.generation
    fun clear() { prefs.edit().clear().commit() }
}

data class UploadReply(val statusCode: Int, val body: String)
fun interface UploadTransport { fun post(target: SyncTarget, payload: String): UploadReply }
class HttpsUploadTransport(private val socketFactory: SSLSocketFactory? = null) : UploadTransport {
    override fun post(target: SyncTarget, payload: String): UploadReply {
        val connection = URL("${target.server}/v1/messages/batch").openConnection() as HttpsURLConnection
        try {
            val pinned = if (target.localCa.isNotBlank()) {
                require(connection.url.host == "localhost" && connection.url.port == 8443)
                val certificate = CertificateFactory.getInstance("X.509").generateCertificate(target.localCa.byteInputStream())
                val trust = KeyStore.getInstance(KeyStore.getDefaultType()).apply { load(null); setCertificateEntry("radar-local", certificate) }
                val managers = TrustManagerFactory.getInstance(TrustManagerFactory.getDefaultAlgorithm()).apply { init(trust) }
                SSLContext.getInstance("TLS").apply { init(null, managers.trustManagers, null) }.socketFactory
            } else null
            (socketFactory ?: pinned)?.let { connection.sslSocketFactory = it }
            connection.requestMethod = "POST"
            connection.instanceFollowRedirects = false
            connection.connectTimeout = 15000; connection.readTimeout = 20000
            connection.doOutput = true
            connection.setRequestProperty("Authorization", "Bearer ${target.token}")
            connection.setRequestProperty("Content-Type", "application/json; charset=utf-8")
            val bytes = payload.toByteArray(Charsets.UTF_8)
            connection.setFixedLengthStreamingMode(bytes.size)
            connection.outputStream.use { it.write(bytes) }
            val code = connection.responseCode
            if (code != 200) return UploadReply(code, "") // Error bodies can contain private data.
            val body = connection.inputStream.use { stream ->
                val output = ByteArrayOutputStream()
                val buffer = ByteArray(4096)
                while (true) {
                    val count = stream.read(buffer)
                    if (count == -1) break
                    require(output.size() + count <= 131072)
                    output.write(buffer,0,count)
                }
                output.toString("UTF-8")
            }
            return UploadReply(code, body)
        } finally { connection.disconnect() }
    }
}

enum class SyncOutcome { IDLE, SENT, RETRY, AUTH_REQUIRED, PROTOCOL_ERROR, CANCELLED }
class SyncEngine(private val db: RadarDatabase, private val transport: UploadTransport) {
    fun sync(target: SyncTarget, isCurrent: () -> Boolean = { true }): SyncOutcome {
        if (!isCurrent()) return SyncOutcome.CANCELLED
        val items = mutableListOf<SavedMessage>()
        var size = 20
        for (message in db.dao().pending(target.room)) {
            val bytes = wire(message).toString().toByteArray(Charsets.UTF_8).size + 1
            if (bytes > 900000) {
                db.runInTransaction {
                    val at=System.currentTimeMillis()
                    db.dao().uploadResult(message.eventId,"rejected","client_item_too_large",at)
                    db.dao().diagnostic(Diagnostic(at=at,code="upload_rejected"))
                }
                continue
            }
            if (size + bytes > 900000) break
            items.add(message); size += bytes
        }
        if (items.isEmpty()) return SyncOutcome.IDLE
        val payload = JSONObject().put("items", JSONArray(items.map { wire(it) })).toString()
        db.dao().attempted(items.map { it.eventId }, System.currentTimeMillis())
        val reply = try { transport.post(target, payload) } catch (_: Exception) { return SyncOutcome.RETRY }
        if (!isCurrent()) return SyncOutcome.CANCELLED
        if (reply.statusCode in listOf(401,403)) return SyncOutcome.AUTH_REQUIRED
        if (reply.statusCode == 429 || reply.statusCode >= 500) return SyncOutcome.RETRY
        if (reply.statusCode != 200) return SyncOutcome.PROTOCOL_ERROR
        val results = runCatching {
            val array = JSONObject(reply.body).getJSONArray("results")
            require(array.length() == items.size)
            val rows = (0 until array.length()).map { array.getJSONObject(it) }
            val ids = rows.map { it.getString("event_id") }
            require(ids.toSet().size == rows.size && ids.toSet() == items.map { it.eventId }.toSet())
            require(rows.all { it.getString("status") in listOf("accepted","duplicate","rejected") })
            rows
        }.getOrElse { return SyncOutcome.PROTOCOL_ERROR }
        db.runInTransaction {
            val at = System.currentTimeMillis()
            results.forEach {
                val status = it.getString("status")
                val reason = it.optString("reason", "")
                val safeReason = if (reason in listOf("room_not_allowed","expired","event_id_conflict","invalid_message")) reason else "server_rejected"
                db.dao().uploadResult(it.getString("event_id"), if (status == "rejected") "rejected" else "sent",
                    if (status == "rejected") safeReason else "", at)
                db.dao().diagnostic(Diagnostic(at = at, code = "upload_$status"))
            }
        }
        return SyncOutcome.SENT
    }
    companion object {
        fun wire(m: SavedMessage) = JSONObject().put("event_id",m.eventId).put("room_id",m.roomId)
            .put("sender_alias",m.sender).put("text",m.text).put("source_time",m.sourceTime ?: JSONObject.NULL)
            .put("observed_at",m.observedAt).put("urls",JSONArray(m.urlsJson)).put("quality",m.quality)
            .put("parser_version",m.parserVersion)
    }
}

class UploadWorker(context: Context, params: WorkerParameters) : Worker(context, params) {
    override fun doWork(): Result {
        val app = applicationContext as RadarApp
        return synchronized(app.syncLock) {
            val target = try { app.syncSettings.snapshot() } catch (_: Exception) {
                app.syncSettings.enabled = false
                app.syncSettings.error = "인증 정보를 다시 설정해 주세요"
                return@synchronized Result.failure()
            } ?: return@synchronized Result.success()
            if (target.room != app.config.roomId || app.config.binding == null) return@synchronized Result.success()
            val engine = SyncEngine(app.db, HttpsUploadTransport())
            for (batch in 0 until 10) {
                if (isStopped) return@synchronized Result.retry()
                val outcome = engine.sync(target) { app.syncSettings.current(target) && app.config.roomId == target.room }
                when (outcome) {
                    SyncOutcome.IDLE, SyncOutcome.CANCELLED -> return@synchronized Result.success()
                    SyncOutcome.SENT -> { app.syncSettings.lastSync = System.currentTimeMillis(); app.syncSettings.error = "" }
                    SyncOutcome.RETRY -> {
                        app.syncSettings.error = "연결 실패 · 대기열을 유지하고 재시도합니다"
                        return@synchronized Result.retry()
                    }
                    SyncOutcome.AUTH_REQUIRED -> {
                        app.syncSettings.enabled = false; app.syncSettings.error = "서버 인증을 다시 설정해 주세요"
                        return@synchronized Result.failure()
                    }
                    SyncOutcome.PROTOCOL_ERROR -> {
                        app.syncSettings.enabled = false; app.syncSettings.error = "서버 응답 형식 오류 · 대기열을 유지합니다"
                        return@synchronized Result.failure()
                    }
                }
            }
            // Continue a large backlog under the same persistent WorkManager request.
            Result.retry()
        }
    }
}

object SyncScheduler {
    private val constraints get() = Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build()
    fun schedule(context: Context) {
        val work = WorkManager.getInstance(context)
        work.enqueueUniquePeriodicWork("radar-sync-periodic", ExistingPeriodicWorkPolicy.KEEP,
            PeriodicWorkRequestBuilder<UploadWorker>(15, TimeUnit.MINUTES).setConstraints(constraints)
                .setBackoffCriteria(BackoffPolicy.EXPONENTIAL,30,TimeUnit.SECONDS).build())
        kick(context)
    }
    fun kick(context: Context) {
        WorkManager.getInstance(context).enqueueUniqueWork("radar-sync-now",ExistingWorkPolicy.KEEP,
            OneTimeWorkRequestBuilder<UploadWorker>().setConstraints(constraints)
                .setBackoffCriteria(BackoffPolicy.EXPONENTIAL,30,TimeUnit.SECONDS).build())
    }
    fun cancel(context: Context) {
        WorkManager.getInstance(context).cancelUniqueWork("radar-sync-periodic")
        WorkManager.getInstance(context).cancelUniqueWork("radar-sync-now")
    }
}
