package dev.kakaoradar.collector

import android.os.Bundle
import androidx.test.platform.app.InstrumentationRegistry
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeTrue
import org.junit.Test

/** Runs one real, already-authorized sync batch without printing credentials or message data. */
class DeviceLiveSyncTest {
    @Test fun syncOneSelectedRoomWithExistingConfiguration() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val app = instrumentation.targetContext.applicationContext as RadarApp
        val target = app.syncSettings.snapshot()
        assertNotNull("Existing sync configuration is required", target)
        val bindings = app.config.bindings
        assertTrue("At least one selected room is required", bindings.isNotEmpty())

        val roomId = bindings.first().roomId
        val outcome = SyncEngine(app.db, HttpsUploadTransport()).sync(target!!, roomId) {
            app.syncSettings.current(target) && app.config.bindings.any { it.roomId == roomId }
        }
        val pending = app.db.dao().queueCount("pending")
        val report = JSONObject()
            .put("outcome", outcome.name)
            .put("pending_after_batch", pending)
            .put("sync_enabled", app.syncSettings.enabled)
            .toString()
        instrumentation.sendStatus(0, Bundle().apply { putString("stream", "SAFE_LIVE_SYNC=$report\n") })
    }

    @Test fun drainAllSelectedRoomsRoundRobin() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        assumeTrue(
            "Explicit backlog drain action is required",
            InstrumentationRegistry.getArguments().getString("action") == "drain_multi_room_backlog"
        )
        val app = instrumentation.targetContext.applicationContext as RadarApp
        val target = app.syncSettings.snapshot()
        assertNotNull("Existing sync configuration is required", target)
        val bindings = app.config.bindings
        assertTrue("At least two selected rooms are required", bindings.size >= 2)
        val engine = SyncEngine(app.db, HttpsUploadTransport())
        val sentBatches = IntArray(bindings.size)
        var cursor = app.syncSettings.roomCursor.mod(bindings.size)
        var idleRooms = 0
        var terminal: SyncOutcome? = null
        for (batch in 0 until 60) {
            val roomId = bindings[cursor].roomId
            val outcome = engine.sync(target!!, roomId) {
                app.syncSettings.current(target) && app.config.bindings.any { it.roomId == roomId }
            }
            when (outcome) {
                SyncOutcome.SENT -> { sentBatches[cursor]++; idleRooms = 0 }
                SyncOutcome.IDLE -> idleRooms++
                else -> { terminal = outcome; break }
            }
            cursor = (cursor + 1).mod(bindings.size)
            app.syncSettings.roomCursor = cursor
            if (idleRooms >= bindings.size) break
        }
        assertTrue("Backlog drain stopped with $terminal", terminal == null)
        val report = JSONObject()
            .put("selected_room_count", bindings.size)
            .put("sent_batches_per_room", JSONArray(sentBatches.toList()))
            .put("pending_after_drain", app.db.dao().queueCount("pending"))
            .put("sync_enabled", app.syncSettings.enabled)
            .toString()
        instrumentation.sendStatus(0, Bundle().apply {
            putString("stream", "SAFE_MULTI_ROOM_DRAIN=$report\n")
        })
    }
}
