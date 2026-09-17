package dev.kakaoradar.collector

import android.os.Bundle
import androidx.test.platform.app.InstrumentationRegistry
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Test
import java.util.concurrent.TimeUnit

/** Reads aggregate diagnostics on the phone. Never copies the database or raw chat records. */
class DeviceDiagnosticsTest {
    @Test fun reportAggregateDiagnosticsOnDevice() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val app = instrumentation.targetContext.applicationContext as RadarApp
        val report = app.io.submit<String> {
            val dao = app.db.dao()
            val totals = JSONObject()
            listOf("unsupported_kakao_callbacks", "kakao_callbacks", "parsed_callbacks", "discovery_snapshots",
                "parsed_snapshots", "selected_callbacks", "saved_messages", "suppressed_entries",
                "processing_errors", "uncertain_windows", "method_messaging_style_title_fallback",
                "method_messaging_style", "method_extra_messages", "method_standard_extras").forEach {
                totals.put(it, dao.total(it))
            }
            dao.reasons().forEach { totals.put(it.code, it.total) }
            val structures = JSONArray()
            val safeFields = listOf("result", "method", "reason", "group_summary", "group_flag",
                "has_conversation_title", "has_title", "message_count", "has_shortcut", "key_hash",
                "shortcut_hash", "title_hash", "tag_equals_shortcut")
            dao.structures().take(10).forEach { row ->
                val payload = JSONObject(row.payload)
                val safe = JSONObject().put("at", row.at).put("source", row.source)
                safeFields.forEach { key -> if (payload.has(key)) safe.put(key, payload.get(key)) }
                structures.put(safe)
            }
            val version = app.db.openHelper.readableDatabase.version
            assertEquals(3, version)
            JSONObject().put("schema_version", version).put("messages", dao.count())
                .put("candidate_count", app.config.candidates().size)
                .put("distinct_chat_ids",app.config.candidates().filter { it.shortcut.isNotBlank() }.map { it.shortcut }.distinct().size)
                .put("room_selected", app.config.binding != null).put("capture_enabled", app.config.enabled)
                .put("upload_pending",dao.queueCount("pending")).put("upload_sent",dao.queueCount("sent"))
                .put("sync_enabled",app.syncSettings.enabled)
                .put("diagnostics", totals).put("recent_structures", structures).toString()
        }.get(30, TimeUnit.SECONDS)
        instrumentation.sendStatus(0, Bundle().apply { putString("stream", "SAFE_DIAGNOSTICS=$report\n") })
    }
}
