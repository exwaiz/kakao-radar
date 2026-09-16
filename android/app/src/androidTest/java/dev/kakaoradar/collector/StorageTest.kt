package dev.kakaoradar.collector

import androidx.room.Room
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.*
import org.junit.Test
import java.util.UUID

class StorageTest {
    @Test fun persistedSnapshotSurvivesReopenAndTransactionRollsBack() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val name = "test-${UUID.randomUUID()}.db"
        fun open() = Room.databaseBuilder(context, RadarDatabase::class.java, name).build()
        var db = open()
        try {
            db.dao().saveSnapshot(Snapshot("room", "[]", 100))
            db.close(); db = open()
            assertEquals("[]", db.dao().snapshot("room")?.payload)
            runCatching { db.runInTransaction {
                db.dao().saveSnapshot(Snapshot("room", "changed", 101))
                error("simulated interruption")
            } }
            assertEquals("[]", db.dao().snapshot("room")?.payload)
            db.dao().pruneSnapshots(101)
            assertNull(db.dao().snapshot("room"))
        } finally { db.close(); context.deleteDatabase(name) }
    }
}
