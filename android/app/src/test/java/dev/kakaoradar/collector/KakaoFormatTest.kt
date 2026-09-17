package dev.kakaoradar.collector

import android.app.Application
import android.app.Notification
import android.app.Person
import android.database.sqlite.SQLiteDatabase
import android.os.Process
import android.service.notification.StatusBarNotification
import androidx.room.Room
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config as RoboConfig
import java.util.UUID

@RunWith(RobolectricTestRunner::class)
@RoboConfig(sdk = [35], application = Application::class)
class KakaoFormatTest {
    private val context get() = RuntimeEnvironment.getApplication()
    private fun sbn(n: Notification, id: Int = 2) = StatusBarNotification(
        NotificationParser.PACKAGE, NotificationParser.PACKAGE, id, "fixture-tag", 1000, 0, 0, n, Process.myUserHandle(), 13000)
    // Synthetic values, with the real device's field presence/absence. No copied chat text.
    private fun kakaoStyle(): Notification {
        val style = Notification.MessagingStyle(Person.Builder().setName("self-fixture").build())
            .setGroupConversation(true).setConversationTitle("fixture-conversation")
            .addMessage("fixture-message https://example.com", 12345, Person.Builder().setName("fixture-sender").build())
        return Notification.Builder(context, "fixture-channel").setStyle(style).setShortcutId("fixture-chat-id").build().apply {
            extras.remove(Notification.EXTRA_CONVERSATION_TITLE)
            extras.remove("android.hiddenConversationTitle")
            extras.putCharSequence(Notification.EXTRA_TITLE, "fixture-room")
            extras.putBoolean(Notification.EXTRA_IS_GROUP_CONVERSATION, true)
        }
    }
    @Test fun actualObservedMissingConversationTitleNowParses() {
        val parsed = (NotificationParser.parse(sbn(kakaoStyle())) as ParseResult.Success).notification
        assertEquals("fixture-room", parsed.room.title)
        assertEquals("fixture-chat-id", parsed.room.shortcut)
        assertEquals("messaging_style_title_fallback", parsed.method)
        assertEquals(12345L, parsed.messages.single().sourceTime)
        assertEquals("fixture-sender", parsed.messages.single().sender)
        assertEquals("fixture-message https://example.com", parsed.messages.single().text)
    }
    @Test fun absentStyleUserStillReadsRawMessageArray() {
        val n = kakaoStyle().apply {
            extras.remove(Notification.EXTRA_TEMPLATE)
            extras.remove("androidx.core.app.extra.COMPAT_TEMPLATE")
            extras.remove("android.messagingStyleUser")
            extras.remove(Notification.EXTRA_MESSAGING_PERSON)
            extras.remove("android.selfDisplayName")
        }
        val parsed = (NotificationParser.parse(sbn(n)) as ParseResult.Success).notification
        assertEquals("extra_messages", parsed.method)
        assertEquals(1, parsed.messages.size)
    }
    @Test fun explicitPrivateChatCannotUseTitleFallback() {
        val n = kakaoStyle().apply { extras.putBoolean(Notification.EXTRA_IS_GROUP_CONVERSATION, false) }
        assertEquals(ParseResult.Unsupported(ParseReason.NOT_GROUP), NotificationParser.parse(sbn(n)))
    }
    @Test fun unknownGroupCannotBeGuessedFromTitleOrShortcut() {
        val n = Notification.Builder(context, "test").setContentTitle("fixture-room")
            .setContentText("fixture-message").setShortcutId("fixture-chat-id").build()
        assertEquals(ParseResult.Unsupported(ParseReason.GROUP_UNCONFIRMED), NotificationParser.parse(sbn(n)))
    }
    @Test fun titleFallbackNeedsStableConversationIdentity() {
        val n = Notification.Builder.recoverBuilder(context, kakaoStyle()).setShortcutId(null).build()
        assertEquals(ParseResult.Unsupported(ParseReason.UNSAFE_TITLE_FALLBACK), NotificationParser.parse(sbn(n)))
    }
    @Test fun explicitGroupStandardExtrasRetainsTextWithoutGuessingSenderOrTimestamp() {
        val n = Notification.Builder(context, "test").setContentTitle("fixture-room")
            .setContentText("fixture: content: intact").setShortcutId("fixture-chat-id").build()
        n.extras.putBoolean(Notification.EXTRA_IS_GROUP_CONVERSATION, true)
        val parsed = (NotificationParser.parse(sbn(n)) as ParseResult.Success).notification
        assertEquals("standard_extras", parsed.method)
        assertEquals("fixture: content: intact", parsed.messages.single().text)
        assertEquals("", parsed.messages.single().sender)
        assertNull(parsed.messages.single().sourceTime)
    }
    @Test fun emptyGroupContentHasItsOwnReason() {
        val n = Notification.Builder(context, "test").setContentTitle("fixture-room").setShortcutId("fixture-chat-id").build()
        n.extras.putBoolean(Notification.EXTRA_IS_GROUP_CONVERSATION, true)
        assertEquals(ParseResult.Unsupported(ParseReason.NO_TEXT), NotificationParser.parse(sbn(n)))
    }
    @Test fun changingNotificationKeyDoesNotChangeShortcutIdentity() {
        val a = (NotificationParser.parse(sbn(kakaoStyle(), 2)) as ParseResult.Success).notification.room
        val b = (NotificationParser.parse(sbn(kakaoStyle(), 3)) as ParseResult.Success).notification.room
        assertNotEquals(a.key, b.key)
        assertTrue(a.matches(b))
    }
    @Test fun equalTitleDifferentChatIdIsNotSameRoomAndCollisionIsVisible() {
        val config = Config(context)
        config.clear()
        val a = RoomCandidate("same title", "one", "one")
        val b = RoomCandidate("same title", "two", "two")
        config.discover(a); config.discover(b)
        assertFalse(a.matches(b)); assertTrue(config.hasTitleCollision(a))
    }
    @Test fun duplicateDiscoveryRefreshesSameChatInsteadOfAddingRows() {
        val config = Config(context)
        config.clear()
        config.discover(RoomCandidate("same title", "one", "chat"))
        config.discover(RoomCandidate("updated display title", "two", "chat"))
        assertEquals(1, config.candidates().size)
        assertEquals("two", config.candidates().single().key)
        assertEquals("updated display title", config.candidates().single().title)
    }
    @Test fun structuralDiagnosticDoesNotContainFixturePrivateValues() {
        val notification = sbn(kakaoStyle())
        val output = NotificationParser.structure(notification, NotificationParser.parse(notification), Config(context)::alias)
        listOf("fixture-room", "fixture-message", "fixture-sender", "fixture-chat-id", "fixture-tag", "example.com").forEach {
            assertFalse("Raw fixture leaked", output.contains(it))
        }
        val json = JSONObject(output)
        assertFalse(json.getBoolean("has_conversation_title"))
        assertTrue(json.getBoolean("group_flag"))
        assertEquals(1, json.getInt("message_count"))
    }
    @Test fun versionOneDatabaseMigratesWithoutLosingHistory() {
        val name = "migration-${UUID.randomUUID()}.db"
        val path = context.getDatabasePath(name)
        path.parentFile!!.mkdirs()
        val schema = JSONObject(javaClass.classLoader!!.getResourceAsStream("schema-v1.json")!!.bufferedReader().readText()).getJSONObject("database")
        SQLiteDatabase.openOrCreateDatabase(path, null).use { raw ->
            val entities = schema.getJSONArray("entities")
            for (i in 0 until entities.length()) {
                val entity = entities.getJSONObject(i)
                raw.execSQL(entity.getString("createSql").replace("\${TABLE_NAME}", entity.getString("tableName")))
                val indices = entity.getJSONArray("indices")
                for (j in 0 until indices.length()) raw.execSQL(indices.getJSONObject(j).getString("createSql").replace("\${TABLE_NAME}", entity.getString("tableName")))
            }
            raw.execSQL("INSERT INTO diagnostics (at,code,value) VALUES (100,'legacy-test',7)")
            raw.execSQL("INSERT INTO messages VALUES ('old-event','room','fixture-room','alias','fixture-text',100,100,'[]','structured',1)")
            raw.version = 1
        }
        val db = Room.databaseBuilder(context, RadarDatabase::class.java, name).addMigrations(RadarDatabase.MIGRATION_1_2,RadarDatabase.MIGRATION_2_3).allowMainThreadQueries().build()
        try {
            assertEquals(7, db.dao().total("legacy-test"))
            assertEquals(1, db.dao().count())
            assertEquals(1, db.dao().queueCount("pending"))
            db.dao().structure(NotificationStructure(at = 200, source = "test", payload = "{}"))
            assertEquals(1, db.dao().structures().size)
        } finally { db.close(); context.deleteDatabase(name) }
    }
}
