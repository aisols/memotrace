package org.memotrace.recorder.storage

import android.content.ContentProviderOperation
import android.content.ContentResolver
import android.content.ContentUris
import android.content.ContentValues
import android.content.Context
import android.net.Uri
import android.os.Bundle
import android.os.ParcelFileDescriptor
import android.provider.MediaStore
import android.system.ErrnoException
import android.system.Os
import android.system.OsConstants
import android.system.StructStat
import androidx.core.net.toUri
import java.io.FileDescriptor
import java.io.FileNotFoundException
import java.io.IOException
import java.io.InputStream
import java.io.OutputStream

class MediaIdentity(
    val name: String,
    val path: String,
)

class MediaEntry(
    val uri: String,
    val name: String,
    val path: String,
    val owner: String?,
    val pending: Boolean,
    val bytes: Long,
    val trashed: Boolean,
)

/** CameraX borrows stream; the store syncs/closes only AFTER the CameraX disk barrier. */
interface CaptureOutput : AutoCloseable {
    val stream: OutputStream

    fun sync()
}

enum class UnlinkStatus { PROVEN_UNLINKED, STILL_LINKED, UNKNOWN }

/** A retained descriptor provides observations, not a universal POSIX unlink guarantee on FUSE. */
interface UnlinkWitness : AutoCloseable {
    fun status(): UnlinkStatus
}

class UnlinkUnprovenException(
    message: String,
    cause: Throwable? = null,
    val status: UnlinkStatus = UnlinkStatus.UNKNOWN,
) : IOException(message, cause)

/** Provider operations are not a SQLite transaction. Null means absent; errors must throw. */
interface MediaDestination {
    val prefix: String
    val owner: String

    fun insert(identity: MediaIdentity): String

    fun find(identity: MediaIdentity): List<MediaEntry>

    fun inspect(uri: String): MediaEntry?

    fun openWrite(uri: String): CaptureOutput

    fun openRead(uri: String): InputStream

    fun watchUnlink(uri: String): UnlinkWitness

    fun publish(
        uri: String,
        identity: MediaIdentity,
    )

    fun deletePending(
        uri: String,
        identity: MediaIdentity,
    )
}

class AndroidMediaDestination(
    context: Context,
    override val prefix: String = "Pictures/MemoTrace/",
    private val stat: (FileDescriptor) -> StructStat = Os::fstat,
) : MediaDestination {
    private val resolver = context.contentResolver
    override val owner: String = context.packageName
    private val collection = MediaStore.Images.Media.getContentUri(MediaStore.VOLUME_EXTERNAL_PRIMARY)
    private val ownership =
        "${MediaStore.MediaColumns.OWNER_PACKAGE_NAME}=? AND ${MediaStore.MediaColumns.RELATIVE_PATH}=? AND " +
            "${MediaStore.MediaColumns.DISPLAY_NAME}=?"

    override fun insert(identity: MediaIdentity): String =
        checkNotNull(
            resolver.insert(
                collection,
                ContentValues().apply {
                    put(MediaStore.MediaColumns.DISPLAY_NAME, identity.name)
                    put(MediaStore.MediaColumns.RELATIVE_PATH, identity.path)
                    put(MediaStore.MediaColumns.MIME_TYPE, "image/jpeg")
                    put(MediaStore.MediaColumns.IS_PENDING, 1)
                },
            ),
        ) { "media_insert" }.toString()

    override fun find(identity: MediaIdentity): List<MediaEntry> =
        query(collection, ownership, arrayOf(owner, identity.path, identity.name))

    override fun inspect(uri: String): MediaEntry? = query(uri.toUri(), null, null).singleOrNull()

    private fun query(
        uri: Uri,
        selection: String?,
        args: Array<String>?,
    ): List<MediaEntry> {
        val columns = arrayOf("_id", "_display_name", "relative_path", "owner_package_name", "is_pending", "_size", "is_trashed")
        val query =
            Bundle().apply {
                putInt(MediaStore.QUERY_ARG_MATCH_PENDING, MediaStore.MATCH_INCLUDE)
                putInt(MediaStore.QUERY_ARG_MATCH_TRASHED, MediaStore.MATCH_INCLUDE)
                putString(ContentResolver.QUERY_ARG_SQL_SELECTION, selection)
                putStringArray(ContentResolver.QUERY_ARG_SQL_SELECTION_ARGS, args)
            }
        return checkNotNull(resolver.query(uri, columns, query, null)) { "media_query" }.use { rows ->
            buildList {
                while (rows.moveToNext()) {
                    add(
                        MediaEntry(
                            ContentUris.withAppendedId(collection, rows.getLong(0)).toString(),
                            rows.getString(1),
                            rows.getString(2),
                            rows.getString(3),
                            rows.getInt(4) != 0,
                            rows.getLong(5),
                            rows.getInt(6) != 0,
                        ),
                    )
                }
            }
        }
    }

    override fun openWrite(uri: String): CaptureOutput {
        val descriptor = checkNotNull(resolver.openFileDescriptor(uri.toUri(), "rw")) { "media_open" }
        try {
            val output = ParcelFileDescriptor.AutoCloseOutputStream(descriptor)
            return object : CaptureOutput {
                override val stream: OutputStream = output

                override fun sync() {
                    output.flush()
                    Os.fsync(descriptor.fileDescriptor)
                }

                override fun close() = output.close()
            }
        } catch (failure: Exception) {
            descriptor.close()
            throw failure
        }
    }

    override fun openRead(uri: String): InputStream = checkNotNull(resolver.openInputStream(uri.toUri())) { "media_read" }

    override fun watchUnlink(uri: String): UnlinkWitness {
        val descriptor =
            try {
                resolver.openFileDescriptor(uri.toUri(), "r") ?: throw UnlinkUnprovenException("unlink_descriptor_missing")
            } catch (missing: FileNotFoundException) {
                // A MediaStore row can exist before the provider creates its file. Never create it just for cleanup.
                val errno = missing.cause as? ErrnoException
                if (errno != null && errno.errno != OsConstants.ENOENT) throw missing
                throw UnlinkUnprovenException("unlink_descriptor_missing", missing)
            }
        try {
            fun observe(): StructStat? =
                try {
                    stat(descriptor.fileDescriptor)
                } catch (failure: ErrnoException) {
                    // Samsung/FUSE may lose pathname-backed fstat after unlink OR rename. Neither proves unlink.
                    if (failure.errno == OsConstants.ENOENT) null else throw failure
                }
            val original = observe()
            return object : UnlinkWitness {
                override fun status(): UnlinkStatus {
                    val current = observe()
                    if (original == null || current == null || original.st_nlink <= 0 || !OsConstants.S_ISREG(original.st_mode) ||
                        current.st_dev != original.st_dev || current.st_ino != original.st_ino || !OsConstants.S_ISREG(current.st_mode)
                    ) {
                        return UnlinkStatus.UNKNOWN
                    }
                    return when {
                        current.st_nlink == 0L -> UnlinkStatus.PROVEN_UNLINKED
                        current.st_nlink > 0 -> UnlinkStatus.STILL_LINKED
                        else -> UnlinkStatus.UNKNOWN
                    }
                }

                override fun close() = descriptor.close()
            }
        } catch (failure: Exception) {
            descriptor.close()
            throw failure
        }
    }

    override fun publish(
        uri: String,
        identity: MediaIdentity,
    ) {
        check(
            resolver.update(
                uri.toUri(),
                ContentValues().apply { put(MediaStore.MediaColumns.IS_PENDING, 0) },
                "$ownership AND is_pending=1",
                arrayOf(owner, identity.path, identity.name),
            ) == 1,
        ) { "media_publish" }
        // A successful update is the publication acknowledgement. A Gallery observer may
        // already have deleted/trashed/moved the original or revoked access before this query.
        val entry =
            try {
                inspect(uri)
            } catch (_: Exception) {
                return
            }
        check(entry?.pending != true) { "media_not_published" }
    }

    override fun deletePending(
        uri: String,
        identity: MediaIdentity,
    ) {
        // AOSP android-16.0.0_r1 MediaProvider.applyBatch holds the database transaction
        // across BOTH operations. Plain delete does NOT reapply selection at filesystem deletion.
        // Never fall back to plain delete on an assertion, batch or provider failure.
        val selection = "$ownership AND is_pending=1 AND is_trashed=0"
        val args = arrayOf(owner, identity.path, identity.name)
        watchUnlink(uri).use { witness ->
            resolver.applyBatch(
                MediaStore.AUTHORITY,
                arrayListOf(
                    ContentProviderOperation
                        .newAssertQuery(uri.toUri())
                        .withSelection(selection, args)
                        .withExpectedCount(1)
                        .withYieldAllowed(false)
                        .withExceptionAllowed(false)
                        .build(),
                    ContentProviderOperation
                        .newDelete(uri.toUri())
                        .withSelection(selection, args)
                        .withExpectedCount(1)
                        .withYieldAllowed(false)
                        .withExceptionAllowed(false)
                        .build(),
                ),
            )
            // MediaProvider can rename outside its SQL transaction. A deleted row is not unlink proof.
            val status = witness.status()
            if (status != UnlinkStatus.PROVEN_UNLINKED) throw UnlinkUnprovenException("media_unlink_$status", status = status)
        }
    }
}
