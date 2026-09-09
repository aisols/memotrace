package org.memotrace.recorder

import android.content.ContentProvider
import android.content.ContentProviderOperation
import android.content.ContentProviderResult
import android.content.ContentResolver
import android.content.ContentValues
import android.content.pm.ProviderInfo
import android.database.Cursor
import android.database.MatrixCursor
import android.net.Uri
import android.os.Bundle
import android.os.CancellationSignal
import android.os.ParcelFileDescriptor
import android.provider.MediaStore
import android.system.ErrnoException
import android.system.OsConstants
import android.system.StructStat
import androidx.core.net.toUri
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import org.junit.runner.RunWith
import org.memotrace.recorder.storage.AndroidMediaDestination
import org.memotrace.recorder.storage.MediaIdentity
import org.memotrace.recorder.storage.UnlinkStatus
import org.memotrace.recorder.storage.UnlinkUnprovenException
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config
import org.robolectric.shadows.ShadowContentResolver
import java.io.FileNotFoundException
import java.util.UUID

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [36], application = android.app.Application::class)
class AndroidMediaDestinationTest {
    @get:Rule val temporary = TemporaryFolder()
    private lateinit var destination: AndroidMediaDestination
    private lateinit var provider: Provider
    private val identity = MediaIdentity("${UUID.randomUUID()}.jpg", "Pictures/MemoTrace/profile/session/")
    private val uri = "content://media/external_primary/images/media/42"

    inner class Provider : ContentProvider() {
        var inserted: ContentValues? = null
        var queryArgs: Bundle? = null
        var selection: String? = null
        var args: Array<out String>? = null
        var pending = true
        var trashed = false
        var exists = true
        var currentIdentity = identity
        var deleteAfterPublication = false
        var denyAfterPublication = false
        var deleteCalls = 0
        var inBatch = false
        var linked = true
        var leaveLinked = false
        var inode = 42L
        var mode = OsConstants.S_IFREG
        var statErrno: Int? = null
        var statErrnoAfterDelete: Int? = null
        var result = 1
        var nullInsert = false
        var nullQuery = false
        var lie = false
        var denied = false
        var lastCursor: Cursor? = null
        var descriptor: ParcelFileDescriptor? = null
        var lastOpenMode: String? = null
        var openFailure: FileNotFoundException? = null
        val file = temporary.newFile()

        override fun onCreate() = true

        override fun getType(uri: Uri) = "image/jpeg"

        override fun insert(
            uri: Uri,
            values: ContentValues?,
        ): Uri? {
            assertEquals("content://media/external_primary/images/media", uri.toString())
            inserted = values
            return if (nullInsert) null else this@AndroidMediaDestinationTest.uri.toUri()
        }

        override fun query(
            uri: Uri,
            projection: Array<out String>?,
            selection: String?,
            selectionArgs: Array<out String>?,
            sortOrder: String?,
        ): Cursor? = error("expected_scoped_bundle_query")

        override fun query(
            uri: Uri,
            projection: Array<out String>?,
            queryArgs: Bundle?,
            cancellationSignal: CancellationSignal?,
        ): Cursor? {
            this.queryArgs = queryArgs
            if (denied) throw SecurityException("test")
            if (nullQuery) return null
            val values =
                mapOf<String, Any>(
                    "_id" to 42,
                    "_display_name" to currentIdentity.name,
                    "relative_path" to currentIdentity.path,
                    "owner_package_name" to destination.owner,
                    "is_pending" to if (pending) 1 else 0,
                    "_size" to 123L,
                    "is_trashed" to if (trashed) 1 else 0,
                )
            val columns = projection ?: values.keys.toTypedArray()
            return MatrixCursor(columns).apply {
                if (matches(
                        queryArgs?.getString(ContentResolver.QUERY_ARG_SQL_SELECTION),
                        queryArgs?.getStringArray(ContentResolver.QUERY_ARG_SQL_SELECTION_ARGS),
                    )
                ) {
                    addRow(columns.map { values.getValue(it) }.toTypedArray())
                }
                lastCursor = this
            }
        }

        private fun matches(
            selection: String?,
            args: Array<out String>?,
        ): Boolean =
            exists &&
                (
                    selection == null || (
                        args?.toList() == listOf(destination.owner, currentIdentity.path, currentIdentity.name) &&
                            (!selection.contains("is_pending=1") || pending) && (!selection.contains("is_trashed=0") || !trashed)
                    )
                )

        override fun applyBatch(operations: ArrayList<ContentProviderOperation>): Array<ContentProviderResult> {
            assertEquals(2, operations.size)
            assertTrue(operations[0].isAssertQuery && operations[1].isDelete)
            assertTrue(operations.all { !it.isYieldAllowed && !it.isExceptionAllowed })
            inBatch = true
            try {
                return super.applyBatch(operations)
            } finally {
                inBatch = false
            }
        }

        override fun update(
            uri: Uri,
            values: ContentValues?,
            selection: String?,
            selectionArgs: Array<out String>?,
        ): Int {
            this.selection = selection
            args = selectionArgs
            assertEquals(0, values!!.getAsInteger(MediaStore.MediaColumns.IS_PENDING))
            if (!matches(selection, selectionArgs)) return 0
            if (result == 1 && !lie) pending = false
            if (deleteAfterPublication) exists = false
            if (denyAfterPublication) denied = true
            return result
        }

        override fun delete(
            uri: Uri,
            selection: String?,
            selectionArgs: Array<out String>?,
        ): Int {
            this.selection = selection
            args = selectionArgs
            check(inBatch) { "unprotected_delete" }
            deleteCalls++
            if (!matches(selection, selectionArgs)) return 0
            if (result == 1) {
                exists = false
                if (!leaveLinked) linked = false
                statErrno = statErrnoAfterDelete
            }
            return result
        }

        override fun openFile(
            uri: Uri,
            mode: String,
        ): ParcelFileDescriptor {
            lastOpenMode = mode
            if (denied) throw SecurityException("test")
            openFailure?.let { throw it }
            if (mode == "r" && !file.exists()) throw FileNotFoundException("provider_file_not_materialized")
            return ParcelFileDescriptor.open(file, ParcelFileDescriptor.parseMode(mode)).also { descriptor = it }
        }
    }

    @Before fun setup() {
        val context = RuntimeEnvironment.getApplication()
        // Robolectric fstat returns stub zero link counts. Inject explicit contract facts, not fake filesystem proof.
        destination =
            AndroidMediaDestination(context, stat = {
                provider.statErrno?.let { throw ErrnoException("fstat", it) }
                StructStat(
                    1,
                    provider.inode,
                    provider.mode,
                    if (provider.linked) 1 else 0,
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                )
            })
        provider = Provider().apply { attachInfo(context, ProviderInfo().apply { authority = "media" }) }
        ShadowContentResolver.registerProviderInternal("media", provider)
    }

    @Test fun providerReceivesPendingPrimaryImageAndScopedOwnershipPredicates() {
        assertEquals(uri, destination.insert(identity))
        assertEquals(identity.path, provider.inserted!!.getAsString(MediaStore.MediaColumns.RELATIVE_PATH))
        assertEquals(identity.name, provider.inserted!!.getAsString(MediaStore.MediaColumns.DISPLAY_NAME))
        assertEquals("image/jpeg", provider.inserted!!.getAsString(MediaStore.MediaColumns.MIME_TYPE))
        assertEquals(1, provider.inserted!!.getAsInteger(MediaStore.MediaColumns.IS_PENDING))
        assertEquals(uri, destination.find(identity).single().uri)
        assertEquals(MediaStore.MATCH_INCLUDE, provider.queryArgs!!.getInt(MediaStore.QUERY_ARG_MATCH_PENDING))
        assertTrue(provider.queryArgs!!.getString(ContentResolver.QUERY_ARG_SQL_SELECTION)!!.contains("owner_package_name=?"))
        assertTrue(provider.lastCursor!!.isClosed)
        destination.publish(uri, identity)
        assertFalse(destination.inspect(uri)!!.pending)
        assertThrows(Exception::class.java) { destination.deletePending(uri, identity) }
        assertTrue(provider.exists)
        assertEquals(0, provider.deleteCalls)
        provider.pending = true
        destination.deletePending(uri, identity)
        assertTrue(provider.selection!!.endsWith("AND is_pending=1 AND is_trashed=0"))
        assertEquals(listOf(destination.owner, identity.path, identity.name), provider.args!!.toList())
    }

    @Test fun changedIdentityOrTrashedItemFailsBatchAssertionBeforeAnyDelete() {
        provider.currentIdentity = MediaIdentity(identity.name, "Pictures/Moved/")
        assertThrows(Exception::class.java) { destination.deletePending(uri, identity) }
        provider.currentIdentity = identity
        provider.trashed = true
        assertTrue(destination.inspect(uri)!!.trashed)
        assertEquals(MediaStore.MATCH_INCLUDE, provider.queryArgs!!.getInt(MediaStore.QUERY_ARG_MATCH_TRASHED))
        assertThrows(Exception::class.java) { destination.deletePending(uri, identity) }
        assertEquals(0, provider.deleteCalls)
        assertTrue(provider.exists)
    }

    @Test fun acknowledgedPublicationSurvivesObserverDeletionOrAccessLoss() {
        provider.deleteAfterPublication = true
        destination.publish(uri, identity)
        assertNull(destination.inspect(uri))
        provider.exists = true
        provider.pending = true
        provider.deleteAfterPublication = false
        provider.denyAfterPublication = true
        destination.publish(uri, identity)
        assertTrue(provider.exists)
    }

    @Test fun nullErrorsAndUnsuccessfulOrLyingPublicationAreNotSuccess() {
        provider.nullInsert = true
        assertThrows(Exception::class.java) { destination.insert(identity) }
        provider.nullQuery = true
        assertThrows(Exception::class.java) { destination.inspect(uri) }
        provider.nullQuery = false
        provider.denied = true
        assertThrows(SecurityException::class.java) { destination.inspect(uri) }
        assertThrows(SecurityException::class.java) { destination.openWrite(uri) }
        provider.denied = false
        provider.result = 0
        assertThrows(Exception::class.java) { destination.publish(uri, identity) }
        assertThrows(Exception::class.java) { destination.deletePending(uri, identity) }
        provider.result = 1
        provider.lie = true
        assertThrows(Exception::class.java) { destination.publish(uri, identity) }
    }

    @Test fun callerClosesParcelDescriptorAndReadStream() {
        assertNull(provider.descriptor)
        val output = destination.openWrite(uri)
        output.stream.write(byteArrayOf(1, 2, 3))
        assertNotNull(provider.descriptor)
        assertTrue(provider.descriptor!!.fileDescriptor.valid())
        output.close()
        assertThrows(IllegalStateException::class.java) { provider.descriptor!!.fd }
        destination.openRead(uri).use { assertEquals(1, it.read()) }
        assertThrows(IllegalStateException::class.java) { provider.descriptor!!.fd }
    }

    @Test fun deletedProviderRowWithLinkedInodeIsNotSuccessfulCleanup() {
        provider.leaveLinked = true
        assertThrows(UnlinkUnprovenException::class.java) { destination.deletePending(uri, identity) }
        assertFalse(provider.exists)
        assertTrue(provider.linked)
        assertThrows(IllegalStateException::class.java) { provider.descriptor!!.fd }
    }

    @Test fun pendingRowWithoutMaterializedFileIsTypedUnprovenAndNeverCreatedForRecovery() {
        assertTrue(provider.file.delete())
        val failure = assertThrows(UnlinkUnprovenException::class.java) { destination.watchUnlink(uri) }
        assertTrue(failure.cause is FileNotFoundException)
        assertTrue(provider.exists)
        assertFalse(provider.file.exists())
        assertEquals("r", provider.lastOpenMode)
        assertEquals(0, provider.deleteCalls)
    }

    @Test fun unlinkWitnessReportsProxyOrChangedInodeAsUnknownAndCloses() {
        provider.mode = OsConstants.S_IFIFO
        destination.watchUnlink(uri).use { assertEquals(UnlinkStatus.UNKNOWN, it.status()) }
        assertEquals(0, provider.deleteCalls)
        assertThrows(IllegalStateException::class.java) { provider.descriptor!!.fd }
        provider.mode = OsConstants.S_IFREG
        destination.watchUnlink(uri).use {
            provider.inode++
            provider.linked = false
            assertEquals(UnlinkStatus.UNKNOWN, it.status())
        }
    }

    @Test fun fuseEnoentAfterDeleteIsUnknownNotProofAndDescriptorCloses() {
        provider.statErrnoAfterDelete = OsConstants.ENOENT
        val failure = assertThrows(UnlinkUnprovenException::class.java) { destination.deletePending(uri, identity) }
        assertEquals(UnlinkStatus.UNKNOWN, failure.status)
        assertFalse(provider.exists)
        assertThrows(IllegalStateException::class.java) { provider.descriptor!!.fd }
        provider.statErrno = OsConstants.ENOENT
        destination.watchUnlink(uri).use {
            assertEquals(UnlinkStatus.UNKNOWN, it.status())
            provider.statErrno = null
            assertEquals(UnlinkStatus.UNKNOWN, it.status())
        }
    }

    @Test fun badDescriptorAndUnrelatedStatErrorsRemainErrorsNotUncertainty() {
        for (errno in listOf(OsConstants.EBADF, OsConstants.EIO, OsConstants.EACCES)) {
            provider.statErrno = errno
            assertEquals(errno, assertThrows(ErrnoException::class.java) { destination.watchUnlink(uri) }.errno)
            assertThrows(IllegalStateException::class.java) { provider.descriptor!!.fd }
            provider.statErrno = null
            destination.watchUnlink(uri).use {
                provider.statErrno = errno
                assertEquals(errno, assertThrows(ErrnoException::class.java) { it.status() }.errno)
            }
            assertThrows(IllegalStateException::class.java) { provider.descriptor!!.fd }
        }
    }

    @Test fun knownPermissionOrIoCauseFromDescriptorOpenIsNotMissingFileUncertainty() {
        for (errno in listOf(OsConstants.EACCES, OsConstants.EIO, OsConstants.EBADF)) {
            val failure = FileNotFoundException("provider_open_failed").apply { initCause(ErrnoException("open", errno)) }
            provider.openFailure = failure
            assertEquals(failure, assertThrows(FileNotFoundException::class.java) { destination.watchUnlink(uri) })
            assertEquals(0, provider.deleteCalls)
        }
    }
}
