package dev.kakaoradar.collector

import android.os.Bundle
import androidx.test.platform.app.InstrumentationRegistry
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeTrue
import org.junit.Test
import java.util.concurrent.TimeUnit

/** Explicit live-device operation. Reports room UUIDs only; never emits room titles or chat text. */
class DeviceMultiRoomSelectionTest {
    @Test fun selectAllDiscoveredRoomsAndPauseCapture() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val args = InstrumentationRegistry.getArguments()
        assumeTrue(
            "Explicit select-all action is required",
            args.getString("action") == "select_all_discovered_rooms"
        )
        val app = instrumentation.targetContext.applicationContext as RadarApp
        val report = app.io.submit<String> {
            val candidates = app.config.candidates()
            assertTrue("At least two discovered rooms are required", candidates.size >= 2)
            app.config.replaceSelected(candidates)
            val bindings = app.config.bindings
            assertEquals(candidates.size, bindings.size)
            assertEquals(bindings.size, bindings.map { it.roomId }.distinct().size)
            assertFalse("Selection changes must pause capture", app.config.enabled)
            JSONObject()
                .put("candidate_count", candidates.size)
                .put("selected_room_count", bindings.size)
                .put("capture_enabled", app.config.enabled)
                .put("selection_version", app.config.selectionVersion)
                .put("room_ids", JSONArray(bindings.map { it.roomId }))
                .toString()
        }.get(30, TimeUnit.SECONDS)
        instrumentation.sendStatus(0, Bundle().apply {
            putString("stream", "SAFE_MULTI_ROOM_SELECTION=$report\n")
        })
    }

    @Test fun resumeProvisionedMultiRoomCapture() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val args = InstrumentationRegistry.getArguments()
        assumeTrue(
            "Explicit resume action is required",
            args.getString("action") == "resume_provisioned_multi_room_capture"
        )
        val app = instrumentation.targetContext.applicationContext as RadarApp
        val report = app.io.submit<String> {
            val bindings = app.config.bindings
            assertTrue("At least two selected rooms are required", bindings.size >= 2)
            assertTrue("Server sync must already be configured", app.syncSettings.enabled)
            app.config.enabled = true
            JSONObject()
                .put("selected_room_count", bindings.size)
                .put("capture_enabled", app.config.enabled)
                .put("sync_enabled", app.syncSettings.enabled)
                .put("selection_version", app.config.selectionVersion)
                .toString()
        }.get(30, TimeUnit.SECONDS)
        SyncScheduler.schedule(app)
        SyncScheduler.kick(app)
        instrumentation.sendStatus(0, Bundle().apply {
            putString("stream", "SAFE_MULTI_ROOM_RESUME=$report\n")
        })
    }
}
