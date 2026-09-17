package dev.kakaoradar.collector

import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.Robolectric
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config
import java.io.ByteArrayOutputStream
import java.util.concurrent.TimeUnit

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35], application = RadarApp::class)
class CollectorFlowTest {
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

    @Test fun activityLaunchesWithCollectionDisabled() {
        val controller = Robolectric.buildActivity(MainActivity::class.java).setup()
        val activity = controller.get()
        assertFalse((activity.application as RadarApp).config.enabled)
        assertNotNull(activity.findViewById<android.view.View>(android.R.id.content))
        controller.pause().stop().destroy()
    }
}
