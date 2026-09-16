package dev.kakaoradar.collector

import android.app.Application
import android.app.Notification
import android.app.Person
import android.os.Process
import android.service.notification.StatusBarNotification
import androidx.room.Room
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config
import java.util.UUID

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35], application = Application::class)
class AndroidCollectorTest {
    private val context get() = RuntimeEnvironment.getApplication()
    private fun notification(group: Boolean = true, summary: Boolean = false): Notification {
        val me = Person.Builder().setName("self").build()
        val sender = Person.Builder().setName("tester").build()
        val style = Notification.MessagingStyle(me).setConversationTitle("테스트 방")
            .setGroupConversation(group).addMessage("링크 https://example.com/?x=1", 12345, sender)
        return Notification.Builder(context, "test").setSmallIcon(android.R.drawable.ic_dialog_info)
            .setStyle(style).setGroupSummary(summary).setShortcutId("room-one").build()
    }
    private fun sbn(n: Notification, pkg: String = NotificationParser.PACKAGE) = StatusBarNotification(
        pkg, pkg, 1, "tag", 1000, 0, 0, n, Process.myUserHandle(), 13000
    )
    @Test fun groupNotificationPreservesFields() {
        val parsed = NotificationParser.parse(sbn(notification()))!!
        assertEquals("테스트 방", parsed.room.title)
        assertEquals("room-one", parsed.room.shortcut)
        assertEquals(12345L, parsed.messages.single().sourceTime)
        assertEquals("tester", parsed.messages.single().sender)
        assertEquals("링크 https://example.com/?x=1", parsed.messages.single().text)
    }
    @Test fun otherAppsAreRejected() { assertNull(NotificationParser.parse(sbn(notification(), "another.app"))) }
    @Test fun directMessagesAreRejected() { assertNull(NotificationParser.parse(sbn(notification(group = false)))) }
    @Test fun groupSummaryIsRejected() { assertNull(NotificationParser.parse(sbn(notification(summary = true)))) }
    @Test fun plainTitleDoesNotBecomeRoom() {
        val n = Notification.Builder(context, "test").setContentTitle("테스트 방").setContentText("private text").build()
        assertNull(NotificationParser.parse(sbn(n)))
    }
    @Test fun selectedRoomMustMatchIdentityAndTitle() {
        val chosen = RoomCandidate("room", "key-one", "")
        assertFalse(chosen.matches(RoomCandidate("room", "key-two", "")))
        assertFalse(chosen.matches(RoomCandidate("different", "key-one", "")))
        assertTrue(chosen.matches(chosen))
    }
    @Test fun persistedSnapshotAndMessagesAreAtomicAcrossRestart() {
        val name = "test-${UUID.randomUUID()}.db"
        fun open() = Room.databaseBuilder(context, RadarDatabase::class.java, name).allowMainThreadQueries().build()
        var db = open()
        try {
            val message = SavedMessage("event", "room", "test", "alias", "hello", 100, 100, "[]", "structured")
            db.runInTransaction {
                db.dao().insertMessages(listOf(message))
                db.dao().saveSnapshot(Snapshot("room", RadarApp.encodeMessages(listOf(ObservedMessage("alias", "hello", 100))), 100))
            }
            db.close(); db = open()
            assertEquals(1, db.dao().count())
            val old = RadarApp.decodeMessages(db.dao().snapshot("room")!!.payload)
            assertTrue(MessageDiff.compare(old, old).added.isEmpty())
            val failed = runCatching { db.runInTransaction {
                db.dao().insertMessages(listOf(message.copy(eventId = "second")))
                db.dao().saveSnapshot(Snapshot("room", "changed", 101))
                error("simulated interruption")
            } }
            assertTrue(failed.isFailure)
            assertEquals(1, db.dao().count())
            assertEquals(old, RadarApp.decodeMessages(db.dao().snapshot("room")!!.payload))
            db.dao().pruneMessages(101); db.dao().pruneSnapshots(101)
            assertEquals(0, db.dao().count()); assertNull(db.dao().snapshot("room"))
        } finally { db.close(); context.deleteDatabase(name) }
    }
    @Test fun aliasIsStableAndSnapshotEncodingKeepsNullTime() {
        val config = Config(context)
        assertEquals(config.alias("sender"), Config(context).alias("sender"))
        assertNotEquals("sender", config.alias("sender"))
        val messages = listOf(ObservedMessage("alias", "text\n줄", null))
        assertEquals(messages, RadarApp.decodeMessages(RadarApp.encodeMessages(messages)))
        assertEquals("https://example.com/?x=1", RadarApp.urls("https://example.com/?x=1").getString(0))
    }
}
