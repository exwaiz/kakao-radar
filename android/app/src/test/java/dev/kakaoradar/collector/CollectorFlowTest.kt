package dev.kakaoradar.collector

import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config
import java.io.ByteArrayOutputStream
import java.util.concurrent.TimeUnit

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35], application = RadarApp::class)
class CollectorFlowTest {
    @Test fun legacySingleRoomPreferenceMigratesWithoutChangingRoomId() {
        val context = RuntimeEnvironment.getApplication()
        val prefs = context.getSharedPreferences("collector", android.content.Context.MODE_PRIVATE)
        val roomId = java.util.UUID.randomUUID().toString()
        val candidate = JSONObject().put("title", "legacy-room").put("key", "legacy-key")
            .put("shortcut", "legacy-shortcut").put("tag", "")
        prefs.edit().clear().putString("binding", candidate.toString()).putString("room_id", roomId)
            .putLong("last_capture", 1234).commit()
        val migrated = Config(context)
        assertEquals(1, migrated.bindings.size)
        assertEquals(roomId, migrated.bindings.single().roomId)
        assertEquals("legacy-room", migrated.bindings.single().candidate.title)
        assertEquals(1234, migrated.bindings.single().lastCapture)
        assertFalse(prefs.contains("binding"))
        assertFalse(prefs.contains("room_id"))
        migrated.clear()
    }

    @Test fun twoSelectedRoomsKeepIndependentIdentityAndSnapshots() {
        val app = RuntimeEnvironment.getApplication() as RadarApp
        app.io.submit {
            app.config.clear()
            app.db.runInTransaction {
                app.db.dao().clearQueue(); app.db.dao().clearMessages(); app.db.dao().clearSnapshots()
            }
            val first = RoomCandidate("fixture-one", "key-one", "shortcut-one")
            val second = RoomCandidate("fixture-two", "key-two", "shortcut-two")
            app.config.replaceSelected(listOf(first, second))
            val bindings = app.config.bindings
            assertEquals(2, bindings.size)
            assertNotEquals(bindings[0].roomId, bindings[1].roomId)
            app.config.enabled = true
            val now = System.currentTimeMillis()
            app.capture(ParsedNotification(first, listOf(ObservedMessage("sender-one", "message-one", now))), now)
            app.capture(ParsedNotification(second, listOf(ObservedMessage("sender-two", "message-two", now + 1))), now + 1)
            app.capture(ParsedNotification(RoomCandidate("other", "other", "other"),
                listOf(ObservedMessage("sender", "must-not-save", now + 2))), now + 2)
            val recent = app.db.dao().recent()
            assertEquals(2, recent.size)
            assertEquals(bindings.map { it.roomId }.toSet(), recent.map { it.roomId }.toSet())
            assertTrue(bindings.all { app.db.dao().snapshot(it.roomId) != null })
            assertTrue(app.db.dao().roomStatus().all { it.stored == 1 && it.pending == 1 })
        }.get(30, TimeUnit.SECONDS)
    }

    @Test fun capturePauseRoomFilteringAndExportAreConsistent() {
        val app = RuntimeEnvironment.getApplication() as RadarApp
        app.io.submit {
            val room = RoomCandidate("허용 방", "key", "shortcut")
            app.config.select(room)
            val now = System.currentTimeMillis()
            val first = ParsedNotification(room, listOf(ObservedMessage("닉네임", "hello secret", now)))
            app.capture(first, now)
            assertEquals(0, app.db.dao().count())
            app.config.enabled = true
            app.capture(first.copy(room = RoomCandidate("다른 방", "other", "other")), now)
            assertEquals(0, app.db.dao().count())
            app.capture(first, now)
            app.capture(first, now + 1)
            assertEquals(1, app.db.dao().count())
            assertEquals(1, app.db.dao().queueCount("pending"))
            assertFalse(app.db.dao().snapshot(app.config.roomId)!!.payload.contains("hello secret"))
            val second = first.copy(messages = first.messages + ObservedMessage("닉네임", "hello secret", now + 2))
            app.capture(second.copy(room = room.copy(title="updated display title",key="updated key")), now + 2)
            assertEquals(2, app.db.dao().count())
            assertEquals(2, app.db.dao().queueCount("pending"))
            app.config.enabled = false
            app.capture(second.copy(messages = second.messages + ObservedMessage("닉네임", "paused", now + 3)), now + 3)
            assertEquals(2, app.db.dao().count())
            val output = ByteArrayOutputStream()
            app.export(output)
            val rows = output.toString("UTF-8").lineSequence().filter { it.isNotBlank() }.map { JSONObject(it) }.toList()
            val messages = rows.filter { it.getString("type") == "message" }
            assertEquals(2, messages.size)
            assertTrue(messages.all { it.getString("text") == "hello secret" })
            assertTrue(messages.all { it.getString("sender") != "닉네임" })
            assertNotEquals(messages[0].getString("event_id"), messages[1].getString("event_id"))
        }.get(30, TimeUnit.SECONDS)
    }

}
