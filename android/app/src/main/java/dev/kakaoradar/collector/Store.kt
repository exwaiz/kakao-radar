package dev.kakaoradar.collector

import androidx.room.*

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
    val parserVersion: Int = 1
)

@Entity(tableName = "snapshots")
data class Snapshot(@PrimaryKey val roomId: String, val payload: String, val updatedAt: Long)

@Entity(tableName = "diagnostics", indices = [Index("at")])
data class Diagnostic(@PrimaryKey(autoGenerate = true) val id: Long = 0, val at: Long, val code: String, val value: Int = 1)

@Dao
interface RadarDao {
    @Insert fun insertMessages(messages: List<SavedMessage>)
    @Insert(onConflict = OnConflictStrategy.REPLACE) fun saveSnapshot(snapshot: Snapshot)
    @Insert fun diagnostic(item: Diagnostic)
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

@Database(entities = [SavedMessage::class, Snapshot::class, Diagnostic::class], version = 1, exportSchema = true)
abstract class RadarDatabase : RoomDatabase() { abstract fun dao(): RadarDao }
