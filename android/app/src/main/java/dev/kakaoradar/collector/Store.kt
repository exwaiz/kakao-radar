package dev.kakaoradar.collector

import androidx.room.*
import androidx.room.migration.Migration
import androidx.sqlite.db.SupportSQLiteDatabase

@Entity(tableName = "messages", indices = [Index("observedAt")])
data class SavedMessage(
    @PrimaryKey val eventId: String,
    val roomId: String,
    val roomTitle: String,
    val sender: String,
    val text: String,
    val sourceTime: Long?,
    val observedAt: Long,
    val urlsJson: String,
    val quality: String,
    val parserVersion: Int = 2
)

@Entity(tableName = "snapshots")
data class Snapshot(@PrimaryKey val roomId: String, val payload: String, val updatedAt: Long)

@Entity(tableName = "diagnostics", indices = [Index("at")])
data class Diagnostic(@PrimaryKey(autoGenerate = true) val id: Long = 0, val at: Long, val code: String, val value: Int = 1)

@Entity(tableName = "notification_structures")
data class NotificationStructure(@PrimaryKey(autoGenerate = true) val id: Long = 0, val at: Long, val source: String, val payload: String)
data class ReasonTotal(val code: String, val total: Int)

@Entity(tableName = "upload_queue", foreignKeys = [ForeignKey(entity = SavedMessage::class,
    parentColumns = ["eventId"], childColumns = ["eventId"], onDelete = ForeignKey.CASCADE)],
    indices = [Index("state")])
data class UploadEntry(@PrimaryKey val eventId: String, val state: String = "pending",
    val attempts: Int = 0, val updatedAt: Long, val reason: String = "")

@Dao
interface RadarDao {
    @Insert fun insertMessages(messages: List<SavedMessage>)
    @Insert fun enqueue(items: List<UploadEntry>)
    @Query("SELECT m.* FROM messages m INNER JOIN upload_queue q ON m.eventId=q.eventId WHERE q.state='pending' AND m.roomId=:roomId ORDER BY m.observedAt,m.eventId LIMIT 100") fun pending(roomId: String): List<SavedMessage>
    @Query("SELECT COUNT(*) FROM upload_queue WHERE state=:state") fun queueCount(state: String): Int
    @Query("SELECT COUNT(*) FROM messages m INNER JOIN upload_queue q ON m.eventId=q.eventId WHERE q.state IN ('pending','rejected') AND m.observedAt<:cutoff") fun expiredPending(cutoff: Long): Int
    @Query("UPDATE upload_queue SET attempts=attempts+1,updatedAt=:at WHERE eventId IN (:ids) AND state='pending'") fun attempted(ids: List<String>, at: Long)
    @Query("UPDATE upload_queue SET state=:state,reason=:reason,updatedAt=:at WHERE eventId=:id AND state='pending'") fun uploadResult(id: String, state: String, reason: String, at: Long)
    @Query("SELECT * FROM upload_queue WHERE eventId=:id") fun uploadEntry(id: String): UploadEntry?
    @Query("DELETE FROM upload_queue") fun clearQueue()
    @Query("SELECT roomId FROM messages GROUP BY roomId") fun storedRoomIds(): List<String>
    @Insert(onConflict = OnConflictStrategy.REPLACE) fun saveSnapshot(snapshot: Snapshot)
    @Insert fun diagnostic(item: Diagnostic)
    @Insert fun structure(item: NotificationStructure)
    @Query("SELECT * FROM notification_structures ORDER BY id DESC LIMIT 100") fun structures(): List<NotificationStructure>
    @Query("DELETE FROM notification_structures WHERE at < :cutoff OR id NOT IN (SELECT id FROM notification_structures ORDER BY id DESC LIMIT 100)") fun pruneStructures(cutoff: Long)
    @Query("DELETE FROM notification_structures") fun clearStructures()
    @Query("SELECT code, SUM(value) AS total FROM diagnostics WHERE code LIKE 'unsupported_%' AND code != 'unsupported_kakao_callbacks' GROUP BY code ORDER BY total DESC") fun reasons(): List<ReasonTotal>
    @Query("SELECT * FROM snapshots WHERE roomId = :roomId") fun snapshot(roomId: String): Snapshot?
    @Query("SELECT COUNT(*) FROM messages") fun count(): Int
    @Query("SELECT * FROM messages ORDER BY observedAt DESC LIMIT 12") fun recent(): List<SavedMessage>
    @Query("SELECT * FROM messages WHERE observedAt > :after OR (observedAt = :after AND eventId > :afterId) ORDER BY observedAt, eventId LIMIT 500")
    fun page(after: Long, afterId: String): List<SavedMessage>
    @Query("SELECT * FROM diagnostics ORDER BY at, id") fun diagnostics(): List<Diagnostic>
    @Query("SELECT COALESCE(SUM(value),0) FROM diagnostics WHERE code = :code") fun total(code: String): Int
    @Query("DELETE FROM messages WHERE observedAt < :cutoff") fun pruneMessages(cutoff: Long): Int
    @Query("DELETE FROM snapshots WHERE updatedAt < :cutoff") fun pruneSnapshots(cutoff: Long)
    @Query("DELETE FROM diagnostics WHERE at < :cutoff") fun pruneDiagnostics(cutoff: Long)
    @Query("DELETE FROM diagnostics WHERE id NOT IN (SELECT id FROM diagnostics ORDER BY id DESC LIMIT 5000)") fun trimDiagnostics()
    @Query("DELETE FROM messages") fun clearMessages()
    @Query("DELETE FROM snapshots") fun clearSnapshots()
    @Query("DELETE FROM diagnostics") fun clearDiagnostics()
}

@Database(entities = [SavedMessage::class, Snapshot::class, Diagnostic::class, NotificationStructure::class, UploadEntry::class], version = 3, exportSchema = true)
abstract class RadarDatabase : RoomDatabase() {
    abstract fun dao(): RadarDao
    companion object {
        val MIGRATION_2_3 = object : Migration(2, 3) {
            override fun migrate(db: SupportSQLiteDatabase) {
                db.execSQL("CREATE TABLE IF NOT EXISTS `upload_queue` (`eventId` TEXT NOT NULL, `state` TEXT NOT NULL, `attempts` INTEGER NOT NULL, `updatedAt` INTEGER NOT NULL, `reason` TEXT NOT NULL, PRIMARY KEY(`eventId`), FOREIGN KEY(`eventId`) REFERENCES `messages`(`eventId`) ON UPDATE NO ACTION ON DELETE CASCADE)")
                db.execSQL("CREATE INDEX IF NOT EXISTS `index_upload_queue_state` ON `upload_queue` (`state`)")
                // Existing records are queued, but network sync remains opt-in and room-scoped.
                db.execSQL("INSERT INTO upload_queue(eventId,state,attempts,updatedAt,reason) SELECT eventId,'pending',0,observedAt,'' FROM messages")
            }
        }
        val MIGRATION_1_2 = object : Migration(1, 2) {
            override fun migrate(db: SupportSQLiteDatabase) {
                db.execSQL("CREATE TABLE IF NOT EXISTS `notification_structures` (`id` INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, `at` INTEGER NOT NULL, `source` TEXT NOT NULL, `payload` TEXT NOT NULL)")
            }
        }
    }
}
