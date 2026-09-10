package org.memotrace.recorder.storage

import android.content.ContentValues
import android.database.Cursor
import android.database.DatabaseErrorHandler
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteDatabaseCorruptException
import android.os.StatFs
import android.os.SystemClock
import androidx.core.database.sqlite.transaction
import org.memotrace.capture.CaptureSession
import java.io.File
import java.nio.channels.FileChannel
import java.nio.file.StandardOpenOption
import java.util.UUID

class FrameRequest(
    val wallMs: Long,
    val elapsedMs: Long,
    val intervalMs: Long,
    val settings: String,
    val cover: String,
    val session: CaptureSession,
    val negotiatedWidth: Int?,
    val negotiatedHeight: Int?,
)

class PendingFrame(
    val id: String,
    val uri: String,
    val identity: MediaIdentity,
    val output: CaptureOutput,
)

enum class Availability { AVAILABLE, MISSING, CHANGED, INACCESSIBLE, TRASHED, LEGACY_PRIVATE, CLEANUP_UNPROVEN }

class SavedFrame(
    val uri: String?,
    val path: String?,
    val bytes: Long?,
    val width: Int?,
    val height: Int?,
    val availability: Availability,
    val profileId: String? = null,
)

class CommittedFrame(
    val savedWallMs: Long,
    val frame: SavedFrame,
)

class ArchiveSummary(
    val count: Long,
    val lastSavedMs: Long?,
    val last: SavedFrame? = null,
    val quarantinedCount: Long = 0,
    val sessionCount: Long = 0,
)

class ViewerFrame(
    val uri: String,
    val bytes: Long?,
    val width: Int?,
    val height: Int?,
)

/** Only the application's serial IO executor may use this store. Recovery is startup-only. */
class FrameStore(
    private val root: File,
    private val media: MediaDestination,
    private val availableBytes: () -> Long = { StatFs(root.path).availableBytes },
    private val checkpoint: (String) -> Unit = {},
) : AutoCloseable {
    private val database: SQLiteDatabase
    private lateinit var journal: SessionJournal
    private var acquisitionStarted = false
    private var frameRecoveryCompleted = false

    init {
        if (!root.isDirectory) {
            check(root.mkdirs()) { "archive_directory" }
            FileChannel.open(root.parentFile!!.toPath(), StandardOpenOption.READ).use { it.force(true) }
        }
        database =
            SQLiteDatabase.openDatabase(
                File(root, "index.sqlite").path,
                null,
                SQLiteDatabase.CREATE_IF_NECESSARY,
                DatabaseErrorHandler { throw SQLiteDatabaseCorruptException("archive_corrupt") },
            )
        try {
            database.execSQL("PRAGMA synchronous=FULL")
            database.rawQuery("PRAGMA journal_mode=DELETE", null).use {
                check(it.moveToFirst() && it.getString(0).equals("delete", ignoreCase = true)) { "journal_mode" }
            }
            check(database.version in 0..4) { "unsupported_archive_version" }
            val previousVersion = database.version
            database.transaction {
                database.execSQL(
                    """
                    CREATE TABLE IF NOT EXISTS frames (
                        id TEXT PRIMARY KEY, state INTEGER NOT NULL DEFAULT 0,
                        request_wall_ms INTEGER NOT NULL, request_elapsed_ms INTEGER NOT NULL,
                        interval_ms INTEGER NOT NULL, settings TEXT NOT NULL, cover_shadow TEXT NOT NULL,
                        sha256 TEXT, bytes INTEGER, saved_wall_ms INTEGER, recovered INTEGER NOT NULL DEFAULT 0
                    )
                    """.trimIndent(),
                )
                if (database.version < 2) {
                    for (column in listOf(
                        "locator_kind TEXT NOT NULL DEFAULT 'legacy'",
                        "uri TEXT",
                        "relative_path TEXT",
                        "profile_id TEXT",
                        "session_id TEXT",
                        "requested_width INTEGER",
                        "requested_height INTEGER",
                        "jpeg_quality INTEGER",
                        "negotiated_width INTEGER",
                        "negotiated_height INTEGER",
                        "actual_width INTEGER",
                        "actual_height INTEGER",
                        "validated INTEGER NOT NULL DEFAULT 0",
                        "availability TEXT NOT NULL DEFAULT 'LEGACY_PRIVATE'",
                    )) {
                        database.execSQL("ALTER TABLE frames ADD COLUMN $column")
                    }
                }
                database.execSQL("CREATE INDEX IF NOT EXISTS frames_state ON frames(state)")
                SessionJournal.createSchema(database)
                if (previousVersion == 3) SessionJournal.migrateV3ToV4(database)
                database.version = 4
                checkpoint("migration")
            }
            journal = SessionJournal(database)
            FileChannel.open(root.toPath(), StandardOpenOption.READ).use { it.force(true) }
        } catch (failure: Exception) {
            database.close()
            throw failure
        }
    }

    fun prepare(request: FrameRequest): PendingFrame = prepare(request, null)

    fun prepareCapture(
        attempt: CaptureAttemptStart,
        request: FrameRequest,
    ): PendingFrame {
        require(attempt.sessionId == request.session.id) { "attempt_session" }
        require(attempt.requestWallMs == request.wallMs && attempt.requestElapsedMs == request.elapsedMs) { "attempt_request" }
        require(attempt.requestedIntervalMs == request.intervalMs) { "attempt_interval" }
        return prepare(request, attempt)
    }

    private fun prepare(
        request: FrameRequest,
        attempt: CaptureAttemptStart?,
    ): PendingFrame {
        check(availableBytes() >= RESERVE_BYTES) { "low_disk" }
        acquisitionStarted = true
        val id = UUID.randomUUID().toString()
        val identity = MediaIdentity("$id.jpg", media.prefix + request.session.relativePath)
        val profile = request.session.profile
        val values =
            ContentValues().apply {
                put("id", id)
                put("request_wall_ms", request.wallMs)
                put("request_elapsed_ms", request.elapsedMs)
                put("interval_ms", request.intervalMs)
                put("settings", request.settings)
                put("cover_shadow", request.cover)
                put("locator_kind", "media")
                put("relative_path", identity.path)
                put("profile_id", profile.id)
                put("session_id", request.session.id)
                put("requested_width", profile.width)
                put("requested_height", profile.height)
                put("jpeg_quality", profile.quality)
                put("negotiated_width", request.negotiatedWidth)
                put("negotiated_height", request.negotiatedHeight)
                put("availability", Availability.INACCESSIBLE.name)
            }
        if (attempt == null) {
            database.insertOrThrow("frames", null, values)
            checkpoint("db_frame")
        } else {
            database.transaction {
                journal.beginAttempt(attempt)
                database.insertOrThrow("frames", null, values)
            }
            checkpoint("db_attempt_frame")
        }
        checkpoint("prepared")
        val uri = media.insert(identity)
        checkpoint("media_inserted")
        update(id, ContentValues().apply { put("uri", uri) })
        checkpoint("db_uri")
        checkpoint("uri_saved")
        val entry = checkNotNull(media.inspect(uri)) { "pending_missing" }
        requireOwned(entry, identity)
        check(entry.pending && !entry.trashed) { "output_not_pending" }
        val output = media.openWrite(uri)
        try {
            checkpoint("output_opened")
            return PendingFrame(id, uri, identity, output)
        } catch (failure: Exception) {
            output.close()
            throw failure
        }
    }

    /** Called only after the CameraX disk lane drains, even on abort. */
    fun finish(
        frame: PendingFrame,
        savedWallMs: Long,
    ): CommittedFrame = finish(frame, savedWallMs, null, null)

    fun finishCapture(
        frame: PendingFrame,
        attemptId: String,
        savedWallMs: Long,
        failurePhase: String?,
    ): CommittedFrame = finish(frame, savedWallMs, attemptId, failurePhase)

    private fun finish(
        frame: PendingFrame,
        savedWallMs: Long,
        attemptId: String?,
        failurePhase: String?,
    ): CommittedFrame {
        frame.output.use {
            it.sync()
            checkpoint("file_synced")
        }
        val metadata = JpegMetadata.read { media.openRead(frame.uri) }
        checkpoint("hashed")
        update(
            frame.id,
            ContentValues().apply {
                put("sha256", metadata.hash)
                put("bytes", metadata.bytes)
                put("actual_width", metadata.width)
                put("actual_height", metadata.height)
                put("saved_wall_ms", savedWallMs)
                put("validated", 1)
            },
        )
        checkpoint("db_validated")
        checkpoint("validated")
        requireOwned(checkNotNull(media.inspect(frame.uri)) { "pending_missing" }, frame.identity)
        media.publish(frame.uri, frame.identity)
        checkpoint("published")
        val row = records("id=?", arrayOf(frame.id)).single()
        val committed =
            CommittedFrame(
                savedWallMs,
                SavedFrame(frame.uri, row.path, row.bytes, row.width, row.height, availability(row), row.profileId),
            )
        database.transaction {
            update(
                frame.id,
                ContentValues().apply {
                    put("state", 1)
                    put("availability", committed.frame.availability.name)
                },
            )
            if (attemptId != null) {
                journal.finishAttempt(attemptId, SystemClock.elapsedRealtime(), "SAVED", failurePhase)
            }
        }
        checkpoint(if (attemptId == null) "db_frame_commit" else "db_frame_attempt_commit")
        checkpoint("committed")
        return committed
    }

    fun abandon(frame: PendingFrame) {
        frame.output.close()
        val row = records("id=?", arrayOf(frame.id)).singleOrNull() ?: return
        if (row.state == 1 || row.state == QUARANTINED || row.validated) return
        try {
            cleanup(row)
        } catch (_: UnlinkUnprovenException) {
            // The caller has already drained the writer. Uncertainty is not a write failure or successful image.
            quarantine(row)
        }
    }

    fun recover(nowWallMs: Long) {
        check(!acquisitionStarted) { "recovery_requires_startup_quiescence" }
        LegacyArchive(root, database).recover(nowWallMs)
        for (row in records("state=0 AND locator_kind='media'")) {
            val identity = row.identity()
            check(identity.path.startsWith(media.prefix) && !identity.path.contains("..")) { "media_namespace" }
            val entry =
                if (row.uri != null) {
                    media.inspect(row.uri)
                } else {
                    media.find(identity).let {
                        check(it.size <= 1) { "ambiguous_pending_media" }
                        it.singleOrNull()
                    }
                }
            if (!row.validated) {
                var unproven = entry == null
                if (entry != null) {
                    requireOwned(entry, identity)
                    check(entry.pending) { "unexpected_published_original" }
                    try {
                        media.deletePending(entry.uri, identity)
                    } catch (_: UnlinkUnprovenException) {
                        unproven = true
                    }
                }
                if (unproven) {
                    quarantine(row, row.uri ?: entry?.uri)
                } else {
                    database.delete("frames", "id=? AND state=0", arrayOf(row.id))
                }
                continue
            }
            if (entry == null) {
                // Publication may have succeeded and the user then deleted it. Keep the durable metadata.
                update(
                    row.id,
                    ContentValues().apply {
                        put("state", 1)
                        put("recovered", 1)
                        put("availability", Availability.MISSING.name)
                    },
                )
                continue
            }
            if (entry.pending) {
                requireOwned(entry, identity)
                val metadata = JpegMetadata.read { media.openRead(entry.uri) }
                val same =
                    metadata.hash == row.hash && metadata.bytes == row.bytes && metadata.width == row.width && metadata.height == row.height
                check(same) {
                    "validated_pending_changed"
                }
                media.publish(entry.uri, identity)
            }
            update(
                row.id,
                ContentValues().apply {
                    put("uri", entry.uri)
                    put("state", 1)
                    put("recovered", 1)
                },
            )
        }
        reconcile()
        frameRecoveryCompleted = true
    }

    private fun cleanup(row: Record) {
        val identity = row.identity()
        val entry = row.uri?.let { media.inspect(it) }
        if (entry == null) throw UnlinkUnprovenException("pending_absent_unlink_unproven")
        requireOwned(entry, identity)
        if (!entry.pending) return
        media.deletePending(entry.uri, identity)
        database.delete("frames", "id=? AND state=0", arrayOf(row.id))
    }

    private fun quarantine(
        row: Record,
        uri: String? = row.uri,
    ) {
        // DB errors must escape; retaining this record is required before session release.
        update(
            row.id,
            ContentValues().apply {
                put("state", QUARANTINED)
                put("availability", Availability.CLEANUP_UNPROVEN.name)
                put("uri", uri)
            },
        )
    }

    /** Scoped metadata queries only, never opens every historical image on a capture tick. */
    fun reconcile(lastOnly: Boolean = false) {
        val selection = if (lastOnly) "state=1 AND rowid=(SELECT MAX(rowid) FROM frames WHERE state=1)" else "state=1"
        for (row in records(selection)) {
            if (row.kind != "media") continue
            val available = availability(row, lastOnly)
            if (available != row.availability) update(row.id, ContentValues().apply { put("availability", available.name) })
        }
    }

    private fun availability(
        row: Record,
        read: Boolean = false,
    ): Availability =
        try {
            val entry = row.uri?.let { media.inspect(it) }
            when {
                entry == null -> Availability.MISSING
                entry.trashed -> Availability.TRASHED
                entry.pending -> Availability.INACCESSIBLE
                entry.owner != media.owner || entry.name != "${row.id}.jpg" || entry.path != row.path || entry.bytes != row.bytes ->
                    Availability.CHANGED
                else -> {
                    if (read) media.openRead(checkNotNull(row.uri)).use { check(it.read() >= 0) { "media_empty" } }
                    Availability.AVAILABLE
                }
            }
        } catch (_: Exception) {
            Availability.INACCESSIBLE
        }

    fun summary(sessionId: String? = null): ArchiveSummary {
        checkpoint("summary")
        val count =
            database.rawQuery("SELECT COUNT(*) FROM frames WHERE state=1", null).use {
                it.moveToFirst()
                it.getLong(0)
            }
        val row = records("state=1 ORDER BY rowid DESC LIMIT 1").singleOrNull()
        val quarantined =
            database.rawQuery("SELECT COUNT(*) FROM frames WHERE state=$QUARANTINED", null).use {
                it.moveToFirst()
                it.getLong(0)
            }
        val selectedSession =
            sessionId
                ?: database.rawQuery("SELECT id FROM capture_sessions ORDER BY rowid DESC LIMIT 1", null).use {
                    if (it.moveToFirst()) it.getString(0) else null
                }
        val sessionCount =
            selectedSession?.let { id ->
                database.rawQuery("SELECT COUNT(*) FROM frames WHERE state=1 AND session_id=?", arrayOf(id)).use {
                    check(it.moveToFirst())
                    it.getLong(0)
                }
            } ?: 0
        return ArchiveSummary(
            count,
            row?.savedMs,
            row?.let {
                SavedFrame(it.uri, it.path, it.bytes, it.width, it.height, it.availability, it.profileId)
            },
            quarantined,
            sessionCount,
        )
    }

    fun viewerFrame(uri: String): ViewerFrame? {
        val row = records("state=1 AND validated=1 AND availability='AVAILABLE' AND uri=?", arrayOf(uri)).singleOrNull() ?: return null
        return ViewerFrame(uri, row.bytes, row.width, row.height)
    }

    fun startCaptureSession(
        session: SessionStart,
        sample: TelemetrySample,
    ) = journal.start(session, sample)

    fun recoverOpenSessions(recoveryDetectedWallMs: Long): Int {
        check(frameRecoveryCompleted) { "frame_recovery_required" }
        return journal.recoverOpenSessions(recoveryDetectedWallMs)
    }

    fun updateNegotiatedSize(
        sessionId: String,
        width: Int,
        height: Int,
    ) = journal.setNegotiatedSize(sessionId, width, height)

    fun addTelemetrySample(
        sessionId: String,
        sample: TelemetrySample,
    ) = journal.sample(sessionId, sample)

    fun endCaptureSession(
        sessionId: String,
        endWallMs: Long,
        endElapsedMs: Long,
        terminalReason: String,
        completionStatus: String,
        sample: TelemetrySample,
    ) = journal.end(sessionId, endWallMs, endElapsedMs, terminalReason, completionStatus, sample)

    fun beginCaptureAttempt(attempt: CaptureAttemptStart) = journal.beginAttempt(attempt)

    fun failCapturePreparation(
        attempt: CaptureAttemptStart,
        elapsedMs: Long,
        failurePhase: String,
    ) = journal.failPreparation(attempt, elapsedMs, failurePhase)

    fun markCameraInvokeReady(
        attemptId: String,
        frameId: String,
        prepareElapsedMs: Long,
        invokeReadyElapsedMs: Long,
    ) {
        journal.cameraInvokeReady(attemptId, frameId, prepareElapsedMs, invokeReadyElapsedMs)
        checkpoint("db_pre_camera")
        checkpoint("camera_invoke_ready")
    }

    fun markCameraCompleted(
        attemptId: String,
        terminalElapsedMs: Long,
        diskDrainedElapsedMs: Long,
    ) {
        journal.cameraCompleted(attemptId, terminalElapsedMs, diskDrainedElapsedMs)
        checkpoint("db_camera_completed")
        checkpoint("camera_completed")
    }

    fun finishCaptureAttempt(
        attemptId: String,
        elapsedMs: Long,
        result: String,
        failurePhase: String?,
    ) = journal.finishAttempt(attemptId, elapsedMs, result, failurePhase)

    fun diagnostics(
        sessionId: String?,
        nowElapsedMs: Long,
    ): SessionDiagnostics? = journal.diagnostics(sessionId, nowElapsedMs)

    fun report(sessionId: String?): LongRunReport? = journal.report(sessionId)

    private fun requireOwned(
        entry: MediaEntry,
        identity: MediaIdentity,
    ) {
        check(identity.path.startsWith(media.prefix) && !identity.path.contains("..")) { "media_namespace" }
        check(entry.owner == media.owner && entry.name == identity.name && entry.path == identity.path) { "media_ownership" }
    }

    private fun update(
        id: String,
        values: ContentValues,
    ) {
        check(database.update("frames", values, "id=?", arrayOf(id)) == 1) { "missing_frame_record" }
    }

    private fun records(
        where: String,
        args: Array<String>? = null,
    ): List<Record> =
        database.rawQuery("SELECT * FROM frames WHERE $where", args).use { rows ->
            buildList { while (rows.moveToNext()) add(Record(rows)) }
        }

    private class Record(
        row: Cursor,
    ) {
        private fun Cursor.text(name: String): String? = getColumnIndexOrThrow(name).let { if (isNull(it)) null else getString(it) }

        val id = checkNotNull(row.text("id"))
        val state = row.text("state")!!.toInt()
        val kind = row.text("locator_kind")
        val profileId = row.text("profile_id")
        val uri = row.text("uri")
        val path = row.text("relative_path")
        val validated = row.text("validated") == "1"
        val hash = row.text("sha256")
        val bytes = row.text("bytes")?.toLong()
        val width = row.text("actual_width")?.toInt()
        val height = row.text("actual_height")?.toInt()
        val savedMs = row.text("saved_wall_ms")?.toLong()
        val availability = Availability.valueOf(row.text("availability")!!)

        fun identity(): MediaIdentity {
            check(UUID.fromString(id).toString() == id) { "invalid_frame_id" }
            return MediaIdentity("$id.jpg", checkNotNull(path))
        }
    }

    override fun close() = database.close()

    companion object {
        const val QUARANTINED = 2
        const val RESERVE_BYTES = 128L * 1024 * 1024
    }
}
