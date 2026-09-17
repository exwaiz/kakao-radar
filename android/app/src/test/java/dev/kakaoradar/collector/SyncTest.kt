package dev.kakaoradar.collector

import android.app.Application
import androidx.room.Room
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config
import java.io.IOException
import java.util.UUID

@RunWith(RobolectricTestRunner::class)
@Config(sdk=[35],application=Application::class)
class SyncTest {
    private val context get()=RuntimeEnvironment.getApplication()
    private fun message(room: String)=SavedMessage(UUID.randomUUID().toString(),room,"fixture-room","a".repeat(64),"fixture-body",12345,System.currentTimeMillis(),"[]","structured")
    private val target get()=SyncTarget("https://example.com",UUID.randomUUID().toString(),"fixture-room-id","fixture-token","fixture-generation")
    private fun database()=Room.inMemoryDatabaseBuilder(context,RadarDatabase::class.java).allowMainThreadQueries().build()
    private fun withDatabase(block: (RadarDatabase) -> Unit) { val db=database(); try { block(db) } finally { db.close() } }
    private fun seed(db: RadarDatabase,m: SavedMessage) { db.runInTransaction { db.dao().insertMessages(listOf(m)); db.dao().enqueue(listOf(UploadEntry(m.eventId,updatedAt=m.observedAt))) } }
    private fun reply(id: String,status: String)=UploadReply(200,JSONObject().put("results",JSONArray().put(JSONObject().put("event_id",id).put("status",status))).toString())

    @Test fun failedNetworkKeepsSameEventAndRetryAcknowledgesDuplicate() {
        withDatabase { db ->
            val t=target; val m=message(t.room); seed(db,m)
            val failed=SyncEngine(db,UploadTransport { _,payload ->
                assertEquals(m.eventId,JSONObject(payload).getJSONArray("items").getJSONObject(0).getString("event_id"))
                throw IOException("fixture offline")
            })
            assertEquals(SyncOutcome.RETRY,failed.sync(t))
            assertEquals("pending",db.dao().uploadEntry(m.eventId)!!.state)
            assertEquals(1,db.dao().uploadEntry(m.eventId)!!.attempts)
            val retry=SyncEngine(db,UploadTransport { _,payload ->
                assertEquals(m.eventId,JSONObject(payload).getJSONArray("items").getJSONObject(0).getString("event_id"))
                reply(m.eventId,"duplicate")
            })
            assertEquals(SyncOutcome.SENT,retry.sync(t))
            assertEquals("sent",db.dao().uploadEntry(m.eventId)!!.state)
            assertEquals(2,db.dao().uploadEntry(m.eventId)!!.attempts)
            assertEquals(SyncOutcome.IDLE,retry.sync(t))
        }
    }
    @Test fun responseWithWrongEventCannotClearQueue() {
        withDatabase { db ->
            val t=target; val m=message(t.room); seed(db,m)
            assertEquals(SyncOutcome.PROTOCOL_ERROR,SyncEngine(db,UploadTransport { _,_ -> reply("wrong","accepted") }).sync(t))
            assertEquals("pending",db.dao().uploadEntry(m.eventId)!!.state)
        }
    }
    @Test fun onlyCurrentRoomIsSent() {
        withDatabase { db ->
            val t=target; val m=message(t.room); val other=message("other-room"); seed(db,m); seed(db,other)
            val engine=SyncEngine(db,UploadTransport { _,payload ->
                assertEquals(1,JSONObject(payload).getJSONArray("items").length())
                assertFalse(payload.contains("other-room")); assertFalse(payload.contains("fixture-room\""))
                reply(m.eventId,"accepted")
            })
            assertEquals(SyncOutcome.SENT,engine.sync(t))
            assertEquals("pending",db.dao().uploadEntry(other.eventId)!!.state)
        }
    }
    @Test fun authenticationErrorKeepsPending() {
        withDatabase { db ->
            val t=target; val m=message(t.room); seed(db,m)
            assertEquals(SyncOutcome.AUTH_REQUIRED,SyncEngine(db,UploadTransport { _,_ -> UploadReply(401,"") }).sync(t))
            assertEquals("pending",db.dao().uploadEntry(m.eventId)!!.state)
        }
    }
    @Test fun rejectedItemIsNotRetriedAndNeverCopiesServerTextToDiagnostics() {
        withDatabase { db ->
            val t=target; val m=message(t.room); seed(db,m)
            val body=JSONObject().put("results",JSONArray().put(JSONObject().put("event_id",m.eventId).put("status","rejected").put("reason","private-fixture-server-text")))
            assertEquals(SyncOutcome.SENT,SyncEngine(db,UploadTransport { _,_ -> UploadReply(200,body.toString()) }).sync(t))
            assertEquals("rejected",db.dao().uploadEntry(m.eventId)!!.state)
            assertEquals("server_rejected",db.dao().uploadEntry(m.eventId)!!.reason)
            assertTrue(db.dao().pending(t.room).isEmpty())
        }
    }
    @Test fun stopOrConfigurationChangeDuringRequestPreventsAcknowledgment() {
        withDatabase { db ->
            val t=target; val m=message(t.room); seed(db,m)
            var active=true
            val engine=SyncEngine(db,UploadTransport { _,_ -> active=false; reply(m.eventId,"accepted") })
            assertEquals(SyncOutcome.CANCELLED,engine.sync(t) { active })
            assertEquals("pending",db.dao().uploadEntry(m.eventId)!!.state)
        }
    }
    @Test fun pendingQueueSurvivesReopenAndExpiryIsCountable() {
        val name="sync-${UUID.randomUUID()}.db"
        fun open()=Room.databaseBuilder(context,RadarDatabase::class.java,name).allowMainThreadQueries().build()
        var db=open(); val m=message("fixture-room-id")
        try {
            seed(db,m); db.close(); db=open()
            assertEquals(m.eventId,db.dao().pending(m.roomId).single().eventId)
            assertEquals(1,db.dao().expiredPending(m.observedAt+1))
            db.dao().pruneMessages(m.observedAt+1)
            assertEquals(0,db.dao().queueCount("pending"))
        } finally { db.close(); context.deleteDatabase(name) }
    }
    @Test fun malformedOrDuplicateAcknowledgmentsLeaveWholeBatchPending() {
        withDatabase { db ->
            val t=target; val first=message(t.room); val second=message(t.room); seed(db,first); seed(db,second)
            val row=JSONObject().put("event_id",first.eventId).put("status","accepted")
            val body=JSONObject().put("results",JSONArray().put(row).put(row)).toString()
            assertEquals(SyncOutcome.PROTOCOL_ERROR,SyncEngine(db,UploadTransport { _,_ -> UploadReply(200,body) }).sync(t))
            assertEquals(2,db.dao().queueCount("pending"))
        }
    }
    @Test fun largeBacklogIsBoundedAndAllItemsEventuallyAcknowledged() {
        withDatabase { db ->
            val t=target
            val items=(1..120).map { message(t.room) }
            db.runInTransaction {
                db.dao().insertMessages(items)
                db.dao().enqueue(items.map { UploadEntry(it.eventId,updatedAt=it.observedAt) })
            }
            var calls=0
            val engine=SyncEngine(db,UploadTransport { _,payload ->
                calls++
                assertTrue(payload.toByteArray(Charsets.UTF_8).size<=900000)
                val rows=JSONObject(payload).getJSONArray("items")
                assertTrue(rows.length()<=100)
                val results=JSONArray()
                for (i in 0 until rows.length()) results.put(JSONObject().put("event_id",rows.getJSONObject(i).getString("event_id")).put("status","accepted"))
                UploadReply(200,JSONObject().put("results",results).toString())
            })
            assertEquals(SyncOutcome.SENT,engine.sync(t))
            assertEquals(20,db.dao().queueCount("pending"))
            assertEquals(SyncOutcome.SENT,engine.sync(t))
            assertEquals(SyncOutcome.IDLE,engine.sync(t))
            assertEquals(120,db.dao().queueCount("sent")); assertEquals(2,calls)
        }
    }
    @Test fun unsendableOversizedItemIsVisibleAsRejectedWithoutBlockingFollowingItems() {
        withDatabase { db ->
            val t=target; val oversized=message(t.room).copy(text="x".repeat(910000)); val normal=message(t.room)
            seed(db,oversized); seed(db,normal)
            val engine=SyncEngine(db,UploadTransport { _,payload ->
                assertEquals(1,JSONObject(payload).getJSONArray("items").length())
                reply(normal.eventId,"accepted")
            })
            assertEquals(SyncOutcome.SENT,engine.sync(t))
            assertEquals("client_item_too_large",db.dao().uploadEntry(oversized.eventId)!!.reason)
            assertEquals("rejected",db.dao().uploadEntry(oversized.eventId)!!.state)
            assertEquals("sent",db.dao().uploadEntry(normal.eventId)!!.state)
            assertEquals(2,db.dao().count()) // Source record retained for the normal retention window.
        }
    }
}
