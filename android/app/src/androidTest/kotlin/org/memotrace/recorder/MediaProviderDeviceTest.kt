package org.memotrace.recorder

import android.content.ContentValues
import android.content.Context
import android.content.OperationApplicationException
import android.database.sqlite.SQLiteDatabase
import android.graphics.Bitmap
import android.os.Bundle
import android.provider.MediaStore
import androidx.core.net.toUri
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.memotrace.capture.CaptureProfile
import org.memotrace.capture.CaptureSession
import org.memotrace.recorder.storage.AndroidMediaDestination
import org.memotrace.recorder.storage.Availability
import org.memotrace.recorder.storage.CaptureOutput
import org.memotrace.recorder.storage.FrameRequest
import org.memotrace.recorder.storage.FrameStore
import org.memotrace.recorder.storage.MediaDestination
import org.memotrace.recorder.storage.MediaIdentity
import org.memotrace.recorder.storage.UnlinkStatus
import org.memotrace.recorder.storage.UnlinkUnprovenException
import org.memotrace.recorder.ui.FrameViewer
import java.io.File
import java.util.UUID
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

@RunWith(AndroidJUnit4::class)
class MediaProviderDeviceTest {
    private val context get() = InstrumentationRegistry.getInstrumentation().targetContext

    private fun cleanup(namespace: TestMediaNamespace): List<CleanupResidue> {
        val retained = namespace.cleanup()
        assertEquals(retained.isNotEmpty(), namespace.hasProvenance())
        retained.forEach {
            assertTrue(it.status != UnlinkStatus.PROVEN_UNLINKED)
            assertTrue(namespace.hasFixture(it.name))
        }
        return retained
    }

    private fun deletePending(
        namespace: TestMediaNamespace,
        uri: String,
        identity: MediaIdentity,
    ) {
        try {
            namespace.destination.deletePending(uri, identity)
        } catch (uncertain: UnlinkUnprovenException) {
            assertTrue(uncertain.status != UnlinkStatus.PROVEN_UNLINKED)
            assertTrue(namespace.hasFixture(identity.name))
        }
        // Initialized fixture, no other actor: the batch must remove the row even if FUSE cannot prove unlink.
        assertNull(namespace.destination.inspect(uri))
    }

    private fun insert(
        namespace: TestMediaNamespace,
        identity: MediaIdentity,
    ): String {
        val uri = namespace.destination.insert(identity)
        val bitmap = Bitmap.createBitmap(16, 12, Bitmap.Config.ARGB_8888)
        try {
            namespace.destination.openWrite(uri).use {
                assertTrue(bitmap.compress(Bitmap.CompressFormat.JPEG, 90, it.stream))
                it.sync()
            }
        } finally {
            bitmap.recycle()
        }
        return uri
    }

    @Test fun batchRequiresStillPendingIdentityAndNeverDeletesPublishedOrMovedOriginal() {
        val namespace = TestMediaNamespace(context)
        try {
            val identity = MediaIdentity("${UUID.randomUUID()}.jpg", namespace.prefix + "fixture/")
            val uri = insert(namespace, identity)
            val witness = namespace.retainUnlinkWitness(uri)
            deletePending(namespace, uri, identity)
            if (witness.status() != UnlinkStatus.PROVEN_UNLINKED) assertTrue(namespace.hasFixture(identity.name))

            val published = MediaIdentity("${UUID.randomUUID()}.jpg", identity.path)
            val publishedUri = insert(namespace, published)
            assertTrue(namespace.destination.inspect(publishedUri)!!.pending)
            namespace.destination.publish(publishedUri, published)
            assertThrows(Exception::class.java) { namespace.destination.deletePending(publishedUri, published) }
            assertFalse(namespace.destination.inspect(publishedUri)!!.pending)

            val moved = MediaIdentity("${UUID.randomUUID()}.jpg", identity.path)
            val movedUri = insert(namespace, moved)
            val newPath = namespace.prefix + "moved/"
            assertEquals(
                1,
                context.contentResolver.update(
                    movedUri.toUri(),
                    ContentValues().apply {
                        put(MediaStore.MediaColumns.RELATIVE_PATH, newPath)
                    },
                    null,
                    null,
                ),
            )
            assertThrows(Exception::class.java) { namespace.destination.deletePending(movedUri, moved) }
            assertEquals(newPath, namespace.destination.inspect(movedUri)!!.path)
            // Restore only this explicitly registered fixture so exact-identity cleanup can proceed.
            assertEquals(
                1,
                context.contentResolver.update(
                    movedUri.toUri(),
                    ContentValues().apply {
                        put(MediaStore.MediaColumns.RELATIVE_PATH, moved.path)
                    },
                    null,
                    null,
                ),
            )
        } finally {
            cleanup(namespace)
        }
    }

    @Test fun privateLedgerRecoversLostUriButDoesNotDeleteUnregisteredSameOwnerUuidSentinel() {
        val namespace = TestMediaNamespace(context, afterInsert = { error("lost_insert_response") })
        val sentinelNamespace = TestMediaNamespace(context, prefix = namespace.prefix)
        val recovering = TestMediaNamespace(context, id = namespace.id)
        try {
            val identity = MediaIdentity("${UUID.randomUUID()}.jpg", namespace.prefix + "fixture/")
            assertThrows(Exception::class.java) { namespace.destination.insert(identity) }
            val lostUri =
                namespace.destination
                    .find(identity)
                    .single()
                    .uri
            // Materialize only this registered synthetic fixture; no-readable-inode cases retain the ledger instead.
            namespace.destination.openWrite(lostUri).use {
                it.stream.write(byteArrayOf(1))
                it.sync()
            }
            val sentinel = MediaIdentity("${UUID.randomUUID()}.jpg", identity.path)
            val sentinelUri = insert(sentinelNamespace, sentinel)
            sentinelNamespace.destination.publish(sentinelUri, sentinel)
            cleanup(recovering)
            assertNull(namespace.destination.inspect(lostUri))
            assertNotNull(sentinelNamespace.destination.inspect(sentinelUri))
            assertFalse(sentinelNamespace.destination.inspect(sentinelUri)!!.pending)
        } finally {
            cleanup(sentinelNamespace)
        }
    }

    @Test fun concurrentPublishAndPendingCleanupCannotBothSucceed() {
        repeat(5) {
            val namespace = TestMediaNamespace(context)
            val workers = Executors.newFixedThreadPool(2)
            try {
                val identity = MediaIdentity("${UUID.randomUUID()}.jpg", namespace.prefix + "race/")
                val uri = insert(namespace, identity)
                val witness = namespace.retainUnlinkWitness(uri)
                val go = CountDownLatch(1)
                val publish =
                    workers.submit<Result<Unit>> {
                        check(go.await(10, TimeUnit.SECONDS))
                        runCatching { namespace.destination.publish(uri, identity) }
                    }
                val delete =
                    workers.submit<Result<Unit>> {
                        check(go.await(10, TimeUnit.SECONDS))
                        runCatching { namespace.destination.deletePending(uri, identity) }
                    }
                go.countDown()
                workers.shutdown()
                check(workers.awaitTermination(30, TimeUnit.SECONDS)) { "provider_workers_not_drained" }
                val published = publish.get(20, TimeUnit.SECONDS)
                val deleted = delete.get(20, TimeUnit.SECONDS)
                assertFalse("publication and verified unlink cannot both succeed", published.isSuccess && deleted.isSuccess)
                if (published.isSuccess) {
                    assertFalse(namespace.destination.inspect(uri)!!.pending)
                    assertTrue(witness.status() != UnlinkStatus.PROVEN_UNLINKED)
                    assertTrue(
                        deleted.exceptionOrNull() is OperationApplicationException ||
                            deleted.exceptionOrNull() is UnlinkUnprovenException,
                    )
                } else {
                    assertNull(namespace.destination.inspect(uri))
                    assertTrue(deleted.isSuccess || deleted.exceptionOrNull() is UnlinkUnprovenException)
                    if (witness.status() != UnlinkStatus.PROVEN_UNLINKED) assertTrue(namespace.hasFixture(identity.name))
                }
                // The cleanup report records its own observation: UNKNOWN/STILL_LINKED retain the exact ledger entry.
                cleanup(namespace)
            } finally {
                workers.shutdown()
                val drained = workers.awaitTermination(30, TimeUnit.SECONDS)
                namespace.closeWitnesses()
                check(drained) { "provider_workers_not_drained; fixture ledger retained" }
            }
        }
    }

    @Test fun missingRowWithoutWitnessRetainsLedgerRatherThanClaimingPhysicalCleanup() {
        val namespace = TestMediaNamespace(context)
        val identity = MediaIdentity("${UUID.randomUUID()}.jpg", namespace.prefix + "missing/")
        val uri = insert(namespace, identity)
        deletePending(namespace, uri, identity)
        // Simulates a restart/lost witness after the row disappeared. Its private ledger must survive.
        val retained = cleanup(namespace)
        assertEquals(UnlinkStatus.UNKNOWN, retained.single().status)
        assertEquals(identity.name, retained.single().name)
        assertTrue(namespace.hasProvenance())
    }

    @Test fun insertedProviderRowBeforeFirstOpenRecoversReadyWithoutCreatingAFile() {
        val namespace = TestMediaNamespace(context)
        val root = File(context.cacheDir, "unopened-index-${namespace.id}")
        val preferences = "unopened-state-${namespace.id}"
        val readOnlyRecovery =
            object : MediaDestination by namespace.destination {
                override fun openWrite(uri: String): CaptureOutput = error("recovery_must_not_materialize_output")
            }
        val restarted =
            object : RecorderApplication() {
                override val archiveDirectory get() = root
                override val preferencesName get() = preferences

                override fun createDestination() = readOnlyRecovery

                override fun recoverCameraScratch() = Unit

                fun attach(context: Context) = attachBaseContext(context)
            }
        var started = false
        try {
            val session = CaptureSession(CaptureProfile.DEFAULT, 0)
            FrameStore(root, readOnlyRecovery, checkpoint = { if (it == "uri_saved") error("staged_before_first_open") }).use {
                val failure =
                    assertThrows(IllegalStateException::class.java) {
                        it.prepare(FrameRequest(1, 2, 2000, "test-unopened", "SHADOW", session, null, null))
                    }
                assertEquals("staged_before_first_open", failure.message)
            }
            val uri =
                SQLiteDatabase.openDatabase(File(root, "index.sqlite").path, null, SQLiteDatabase.OPEN_READONLY).use { db ->
                    db.rawQuery("SELECT uri FROM frames", null).use {
                        assertTrue(it.moveToFirst())
                        it.getString(0)
                    }
                }
            assertTrue(namespace.destination.inspect(uri)!!.pending)
            val instrument = InstrumentationRegistry.getInstrumentation()
            instrument.runOnMainSync {
                restarted.attach(context)
                restarted.onCreate()
                started = true
            }
            restarted.io.submit {}.get(10, TimeUnit.SECONDS)
            instrument.runOnMainSync {
                assertTrue(restarted.ready)
                assertFalse(restarted.sessionOpen)
                assertEquals(0L, restarted.summary.count)
                assertNull(restarted.summary.last)
                assertNull(restarted.summary.lastSavedMs)
                assertTrue(restarted.summary.quarantinedCount in 0L..1L)
                assertTrue(restarted.selectProfile(CaptureProfile.WIDE_80.id))
                assertTrue(restarted.canStart)
            }
            restarted.io
                .submit {
                    restarted.store.recover(40)
                    assertEquals(restarted.summary.quarantinedCount, restarted.store.summary().quarantinedCount)
                }.get(10, TimeUnit.SECONDS)
            SQLiteDatabase.openDatabase(File(root, "index.sqlite").path, null, SQLiteDatabase.OPEN_READONLY).use { db ->
                db.rawQuery("SELECT state, uri, validated, availability, profile_id, session_id FROM frames", null).use {
                    if (restarted.summary.quarantinedCount == 1L) {
                        assertTrue(it.moveToFirst())
                        assertEquals(FrameStore.QUARANTINED, it.getInt(0))
                        assertEquals(uri, it.getString(1))
                        assertEquals(0, it.getInt(2))
                        assertEquals(Availability.CLEANUP_UNPROVEN.name, it.getString(3))
                        assertEquals(session.profile.id, it.getString(4))
                        assertEquals(session.id, it.getString(5))
                    } else {
                        assertFalse(it.moveToFirst())
                        assertNull(namespace.destination.inspect(uri))
                    }
                }
            }
            // Eager providers may prove removal; lazy/unsupported witnesses quarantine. Neither requires a write.
            // Retain this precisely scoped fixture ledger/index for diagnosis; do not materialize or sweep its output.
            assertTrue(namespace.hasProvenance())
            reportRetained(namespace)
        } finally {
            try {
                if (started) restarted.io.submit { restarted.store.close() }.get(10, TimeUnit.SECONDS)
            } finally {
                restarted.io.shutdown()
                namespace.closeWitnesses()
                context.deleteSharedPreferences(preferences)
            }
        }
    }

    private fun reportRetained(namespace: TestMediaNamespace) {
        InstrumentationRegistry.getInstrumentation().sendStatus(
            0,
            Bundle().apply {
                putString(
                    "stream",
                    "Cleanup NOT proven: retained private media-fixtures-${namespace.id} ledger. No path scan/delete attempted.\n",
                )
            },
        )
    }

    @Test fun realTrashRestoreKeepsHistoryButDisablesViewingWhileTrashed() {
        val namespace = TestMediaNamespace(context)
        val root = File(context.cacheDir, "trash-index-${namespace.id}")
        try {
            FrameStore(root, namespace.destination).use { store ->
                val session = CaptureSession(CaptureProfile.DEFAULT, 0)
                val frame = store.prepare(FrameRequest(1, 2, 2000, "test", "SHADOW", session, 16, 12))
                val bitmap = Bitmap.createBitmap(16, 12, Bitmap.Config.ARGB_8888)
                try {
                    assertTrue(bitmap.compress(Bitmap.CompressFormat.JPEG, 90, frame.output.stream))
                    store.finish(frame, 3)
                } finally {
                    bitmap.recycle()
                    frame.output.close()
                }
                val savedBytes = store.summary().last!!.bytes
                assertEquals(
                    1,
                    context.contentResolver.update(
                        frame.uri.toUri(),
                        ContentValues().apply {
                            put(MediaStore.MediaColumns.IS_TRASHED, 1)
                        },
                        null,
                        null,
                    ),
                )
                store.reconcile(lastOnly = true)
                assertEquals(Availability.TRASHED, store.summary().last!!.availability)
                assertNull(FrameViewer.intent(store.summary().last))
                assertEquals(1L, store.summary().count)
                assertEquals(savedBytes, store.summary().last!!.bytes)
                assertEquals(
                    1,
                    context.contentResolver.update(
                        frame.uri.toUri(),
                        ContentValues().apply {
                            put(MediaStore.MediaColumns.IS_TRASHED, 0)
                        },
                        null,
                        null,
                    ),
                )
                store.reconcile(lastOnly = true)
                assertEquals(Availability.AVAILABLE, store.summary().last!!.availability)
                assertNotNull(FrameViewer.intent(store.summary().last))
            }
        } finally {
            if (cleanup(namespace).isEmpty()) root.deleteRecursively()
        }
    }
}
