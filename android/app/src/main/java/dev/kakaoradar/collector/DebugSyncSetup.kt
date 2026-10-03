package dev.kakaoradar.collector

import android.content.pm.ApplicationInfo
import org.json.JSONObject
import java.io.File

/** Private, one-use ADB setup file for this user's debug installation. No Intent secrets. */
fun RadarApp.consumeDebugSyncSetup() {
    if (applicationInfo.flags and ApplicationInfo.FLAG_DEBUGGABLE == 0) return
    synchronized(syncLock) {
        val file = File(filesDir, "sync-setup.json")
        if (!file.isFile) return
        try {
            require(file.length() in 1..4096)
            val data = JSONObject(file.readText())
            require(config.bindings.isNotEmpty())
            val legacyRoom = data.optString("room", "")
            require(legacyRoom.isBlank() || config.bindings.any { it.roomId == legacyRoom })
            syncSettings.configure(data.getString("server"), data.getString("device"), data.getString("token"), data.optString("ca_pem", ""))
            SyncScheduler.schedule(this)
            SyncScheduler.kick(this)
        } catch (_: Exception) {
            syncSettings.error = "서버 연결 설정을 확인하세요"
        } finally {
            file.delete()
        }
    }
}
