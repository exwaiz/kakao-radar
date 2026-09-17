package dev.kakaoradar.collector

import android.content.ComponentName
import android.os.Bundle
import android.provider.Settings
import android.service.notification.NotificationListenerService
import android.util.Base64
import androidx.test.platform.app.InstrumentationRegistry
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeTrue
import org.junit.Test
import java.util.concurrent.TimeUnit
import java.text.Normalizer

/** Opt-in device setup for an explicitly user-selected room; skipped by normal test runs. */
class DeviceSetupTest {
    @Test fun selectExplicitlyRequestedRoom() {
        val args = InstrumentationRegistry.getArguments()
        val encoded = args.getString("room_filter_base64").orEmpty()
        assumeTrue("Explicit room filter and start action required", encoded.isNotBlank() && args.getString("action") == "start_capture")
        val filter = String(Base64.decode(encoded, Base64.DEFAULT), Charsets.UTF_8)
        require(filter.isNotBlank())
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val app = instrumentation.targetContext.applicationContext as RadarApp
        val access = Settings.Secure.getString(app.contentResolver, "enabled_notification_listeners").orEmpty()
        assertTrue("Notification access must already be granted", access.split(':').any {
            ComponentName.unflattenFromString(it)?.packageName == app.packageName
        })
        val report = app.io.submit<String> {
            fun searchable(value: String) = Normalizer.normalize(value, Normalizer.Form.NFKC)
                .filterNot { it.isWhitespace() || Character.getType(it) == Character.FORMAT.toInt() }
            val matches = app.config.candidates().filter { searchable(it.title).contains(searchable(filter)) }
            assertEquals("Room filter must match exactly one discovered room", 1, matches.size)
            val choice = matches.single()
            assertTrue("Stable room identity required", choice.shortcut.isNotBlank())
            if (app.config.binding?.matches(choice) != true) app.config.select(choice)
            app.config.enabled = true
            JSONObject().put("selected_room", choice.title).put("capture_enabled", app.config.enabled)
                .put("room_id_hash", app.config.alias(app.config.roomId))
                .put("messages_before", app.db.dao().count()).toString()
        }.get(30, TimeUnit.SECONDS)
        NotificationListenerService.requestRebind(ComponentName(app, CollectorService::class.java))
        instrumentation.sendStatus(0, Bundle().apply { putString("stream", "DEVICE_SETUP=$report\n") })
    }
}
