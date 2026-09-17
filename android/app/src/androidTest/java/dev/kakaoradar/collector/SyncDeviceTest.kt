package dev.kakaoradar.collector

import android.content.Context
import androidx.room.Room
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.*
import org.junit.Assume.assumeTrue
import org.junit.Test
import java.io.ByteArrayInputStream
import java.io.IOException
import java.security.KeyStore
import java.security.cert.CertificateFactory
import java.util.UUID
import javax.net.ssl.SSLContext
import javax.net.ssl.TrustManagerFactory
import android.util.Base64

class SyncDeviceTest {
    @Test fun tokenEncryptionAndReopenPreserveOptInSettings() {
        val context=InstrumentationRegistry.getInstrumentation().targetContext
        val name="test-sync-${UUID.randomUUID()}"
        val alias="test-key-${UUID.randomUUID()}"
        val settings=SyncSettings(context,name,alias)
        val token="fixture-token-"+UUID.randomUUID().toString()
        try {
            assertFalse(settings.enabled)
            val device=UUID.randomUUID().toString(); val room=UUID.randomUUID().toString()
            settings.configure("https://example.com",device,room,token)
            val snapshot=settings.snapshot()!!
            assertEquals(token,snapshot.token)
            assertEquals(token,SyncSettings(context,name,alias).snapshot()!!.token)
            assertFalse(context.getSharedPreferences(name,Context.MODE_PRIVATE).all.values.any { it.toString().contains(token) })
            settings.enabled=false
            assertNull(settings.snapshot()); assertFalse(settings.current(snapshot))
        } finally {
            settings.clear(); context.deleteSharedPreferences(name)
            KeyStore.getInstance("AndroidKeyStore").apply { load(null); deleteEntry(alias) }
        }
    }

    @Test fun syntheticHttpsUploadSurvivesLostResponseAndRoomFiltering() {
        val args=InstrumentationRegistry.getArguments()
        val server=args.getString("test_server").orEmpty()
        assumeTrue("Explicit localhost HTTPS fixture required",server=="https://localhost:8443")
        val device=args.getString("test_device")!!; val room=args.getString("test_room")!!
        val token=String(Base64.decode(args.getString("test_token_base64"),Base64.DEFAULT),Charsets.UTF_8)
        val cert=CertificateFactory.getInstance("X.509").generateCertificate(ByteArrayInputStream(Base64.decode(args.getString("test_ca_base64"),Base64.DEFAULT)))
        val trust=KeyStore.getInstance(KeyStore.getDefaultType()).apply { load(null); setCertificateEntry("fixture-ca",cert) }
        val factory=TrustManagerFactory.getInstance(TrustManagerFactory.getDefaultAlgorithm()).apply { init(trust) }
        val tls=SSLContext.getInstance("TLS").apply { init(null,factory.trustManagers,null) }
        val context=InstrumentationRegistry.getInstrumentation().targetContext
        val name="test-https-${UUID.randomUUID()}.db"
        fun open()=Room.databaseBuilder(context,RadarDatabase::class.java,name).build()
        var db=open()
        try {
            val now=System.currentTimeMillis()
            val first=SavedMessage(UUID.randomUUID().toString(),room,"fixture-room","a".repeat(64),"fixture-one https://example.com",now,now,"[\"https://example.com\"]","structured")
            val second=first.copy(eventId=UUID.randomUUID().toString(),text="fixture-two",urlsJson="[]")
            val other=first.copy(eventId=UUID.randomUUID().toString(),roomId=UUID.randomUUID().toString(),text="must-not-upload-fixture")
            val items=listOf(first,second,other)
            db.runInTransaction { db.dao().insertMessages(items); db.dao().enqueue(items.map { UploadEntry(it.eventId,updatedAt=now) }) }
            val target=SyncTarget(server,device,room,token,"fixture")
            val https=HttpsUploadTransport(tls.socketFactory)
            val lost=SyncEngine(db,UploadTransport { t,payload ->
                assertFalse(payload.contains("must-not-upload-fixture"))
                assertEquals(200,https.post(t,payload).statusCode)
                throw IOException("simulated response loss after server commit")
            })
            assertEquals(SyncOutcome.RETRY,lost.sync(target))
            db.close(); db=open()
            assertEquals(3,db.dao().queueCount("pending"))
            assertEquals(SyncOutcome.SENT,SyncEngine(db,https).sync(target))
            assertEquals(2,db.dao().queueCount("sent"))
            assertEquals(2,db.dao().total("upload_duplicate"))
            assertEquals("pending",db.dao().uploadEntry(other.eventId)!!.state)
            assertEquals(SyncOutcome.IDLE,SyncEngine(db,https).sync(target))
        } finally { db.close(); context.deleteDatabase(name) }
    }
}
