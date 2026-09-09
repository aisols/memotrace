package org.memotrace.recorder

import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteException
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import org.junit.runner.RunWith
import org.memotrace.capture.CaptureProfile
import org.memotrace.capture.CaptureSession
import org.memotrace.recorder.storage.Availability
import org.memotrace.recorder.storage.FrameRequest
import org.memotrace.recorder.storage.FrameStore
import org.memotrace.recorder.storage.MediaIdentity
import org.memotrace.recorder.storage.UnlinkUnprovenException
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode
import org.robolectric.shadows.ShadowStatFs
import java.io.File
import java.nio.file.Files
import java.security.MessageDigest
import java.util.UUID

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [36], application = android.app.Application::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
class FrameStoreTest {
    @get:Rule val temporary = TemporaryFolder()
    private val media = FakeMediaDestination()
    private val request =
        FrameRequest(10, 20, 2_000, "synthetic-settings", "SHADOW;true", CaptureSession(CaptureProfile.DEFAULT, 0), 16, 12)
    private val jpeg get() = syntheticJpeg()

    @Before fun freeDisk() {
        ShadowStatFs.registerStats(temporary.root.path, 1_000_000, 500_000, 500_000)
    }

    private fun save(
        store: FrameStore,
        time: Long = 30,
    ): String {
        val frame = store.prepare(request)
        frame.output.stream.write(jpeg)
        store.finish(frame, time)
        return frame.uri
    }

    @Test fun preservesSingleOriginalAndRequestedNegotiatedActualMetadata() {
        val root = temporary.newFolder()
        FrameStore(root, media).use { store ->
            assertNull(store.summary().last)
            val uri = save(store)
            assertArrayEquals(jpeg, media.items.getValue(uri).bytes)
            assertFalse(media.items.getValue(uri).pending)
            assertEquals(1L, store.summary().count)
            assertEquals(30L, store.summary().lastSavedMs)
            assertEquals(16, store.summary().last!!.width)
            assertEquals(12, store.summary().last!!.height)
            assertEquals(0, media.writesOpen)
            assertEquals(0, media.readsOpen)
            assertEquals(1, media.syncs)
            assertFalse(root.listFiles()!!.any { it.extension in listOf("jpg", "part") })
        }
        SQLiteDatabase.openDatabase(File(root, "index.sqlite").path, null, SQLiteDatabase.OPEN_READONLY).use { db ->
            db
                .rawQuery(
                    "SELECT requested_width, requested_height, jpeg_quality, negotiated_width, " +
                        "negotiated_height, profile_id, sha256 FROM frames",
                    null,
                ).use {
                    assertTrue(it.moveToFirst())
                    assertEquals(1440, it.getInt(0))
                    assertEquals(1080, it.getInt(1))
                    assertEquals(90, it.getInt(2))
                    assertEquals(16, it.getInt(3))
                    assertEquals(12, it.getInt(4))
                    assertEquals(request.session.profile.id, it.getString(5))
                    assertEquals(
                        MessageDigest.getInstance("SHA-256").digest(jpeg).joinToString("") { byte -> "%02x".format(byte) },
                        it.getString(6),
                    )
                }
        }
    }

    @Test fun processDeathAtEveryCrossingRecoversIdempotently() {
        for (boundary in listOf(
            "prepared",
            "media_inserted",
            "uri_saved",
            "output_opened",
            "file_synced",
            "hashed",
            "validated",
            "published",
            "committed",
        )) {
            val root = temporary.newFolder()
            val backend = FakeMediaDestination()
            FrameStore(root, backend, checkpoint = { if (it == boundary) error("death") }).use { store ->
                assertThrows(IllegalStateException::class.java) { save(store) }
            }
            assertEquals(boundary, 0, backend.writesOpen)
            FrameStore(root, backend).use { store ->
                store.recover(40)
                store.recover(50)
                val retained = boundary in listOf("validated", "published", "committed")
                val quarantined = boundary in listOf("prepared", "media_inserted", "uri_saved")
                assertEquals(boundary, if (retained) 1L else 0L, store.summary().count)
                assertEquals(boundary, if (quarantined) 1L else 0L, store.summary().quarantinedCount)
                assertEquals(if (retained || (quarantined && boundary != "prepared")) 1 else 0, backend.items.size)
                if (quarantined) {
                    assertNull(store.summary().last)
                    assertNull(store.summary().lastSavedMs)
                    assertFalse(backend.items.values.any { it.linked })
                }
                if (retained) {
                    assertArrayEquals(
                        jpeg,
                        backend.items.values
                            .single()
                            .bytes,
                    )
                }
            }
        }
    }

    @Test fun providerFaultsAreNotSuccessAndAllOwnedResourcesClose() {
        for (fault in listOf(
            "insert",
            "insert_after",
            "open_write",
            "write",
            "sync",
            "close",
            "open_read",
            "read",
            "inspect",
            "publish",
            "publish_after",
        )) {
            val root = temporary.newFolder()
            val backend = FakeMediaDestination().apply { this.fault = fault }
            FrameStore(root, backend).use { store ->
                assertThrows(Exception::class.java) {
                    val frame = store.prepare(request)
                    try {
                        frame.output.stream.write(jpeg)
                        store.finish(frame, 30)
                    } finally {
                        frame.output.close()
                    }
                }
                assertEquals(fault, 0L, store.summary().count)
            }
            assertEquals(fault, 0, backend.writesOpen)
            assertEquals(fault, 0, backend.readsOpen)
            backend.fault = null
            FrameStore(root, backend).use {
                it.recover(40)
                it.recover(50)
                val quarantined = fault in listOf("insert", "insert_after", "open_write", "inspect")
                assertEquals(fault, if (quarantined) 1L else 0L, it.summary().quarantinedCount)
            }
            assertFalse(backend.items.values.any { it.pending && it.linked })
        }
    }

    @Test fun deletedRowWithStillLinkedArtifactKeepsQuarantinedProvenanceAcrossRestarts() {
        val root = temporary.newFolder()
        var id = ""
        FrameStore(root, media).use { store ->
            val frame = store.prepare(request)
            id = frame.id
            frame.output.stream.write(jpeg)
            val artifact = media.items.getValue(frame.uri)
            media.leaveLinkedOnDelete = true
            store.abandon(frame)
            assertEquals(1L, store.summary().quarantinedCount)
            assertEquals(0L, store.summary().count)
            assertTrue(media.items.isEmpty())
            assertTrue(artifact.linked)
            assertEquals(0, media.witnessesOpen)
        }
        FrameStore(root, media).use {
            it.recover(40)
            it.recover(50)
            assertEquals(1L, it.summary().quarantinedCount)
            assertEquals(0L, it.summary().count)
        }
        SQLiteDatabase.openDatabase(File(root, "index.sqlite").path, null, SQLiteDatabase.OPEN_READONLY).use { db ->
            db.rawQuery("SELECT state, profile_id, uri FROM frames WHERE id=?", arrayOf(id)).use {
                assertTrue(it.moveToFirst())
                assertEquals(FrameStore.QUARANTINED, it.getInt(0))
                assertEquals(request.session.profile.id, it.getString(1))
                assertFalse(it.isNull(2))
            }
        }
    }

    @Test fun absentOrUnmaterializedOldOutputIsQuarantinedOnceAndNewSaveRemainsSeparate() {
        for (phase in listOf("prepared", "media_inserted", "uri_saved")) {
            val root = temporary.newFolder()
            val backend = FakeMediaDestination()
            FrameStore(root, backend, checkpoint = { if (it == phase) error("death") }).use {
                assertThrows(IllegalStateException::class.java) { it.prepare(request) }
            }
            assertFalse(backend.items.values.any { it.linked })
            FrameStore(root, backend).use {
                it.recover(40)
                assertEquals(1L, it.summary().quarantinedCount)
                assertEquals(0L, it.summary().count)
            }
            backend.beforeInspect = { throw AssertionError("quarantine_must_not_be_queried_again") }
            backend.fault = "find"
            FrameStore(root, backend).use {
                it.recover(50)
                it.reconcile()
                it.reconcile(lastOnly = true)
                assertEquals(1L, it.summary().quarantinedCount)
                backend.beforeInspect = {}
                backend.fault = null
                save(it, 60)
                assertEquals(1L, it.summary().count)
                assertEquals(60L, it.summary().lastSavedMs)
                assertEquals(1L, it.summary().quarantinedCount)
            }
            SQLiteDatabase.openDatabase(File(root, "index.sqlite").path, null, SQLiteDatabase.OPEN_READONLY).use { db ->
                db
                    .rawQuery(
                        "SELECT id, relative_path, profile_id, session_id, uri, availability, validated, saved_wall_ms " +
                            "FROM frames WHERE state=?",
                        arrayOf(FrameStore.QUARANTINED.toString()),
                    ).use {
                        assertTrue(it.moveToFirst())
                        UUID.fromString(it.getString(0))
                        assertEquals(backend.prefix + request.session.relativePath, it.getString(1))
                        assertEquals(request.session.profile.id, it.getString(2))
                        assertEquals(request.session.id, it.getString(3))
                        assertEquals(phase == "prepared", it.isNull(4))
                        assertEquals(Availability.CLEANUP_UNPROVEN.name, it.getString(5))
                        assertEquals(0, it.getInt(6))
                        assertTrue(it.isNull(7))
                        assertFalse(it.moveToNext())
                    }
            }
        }
    }

    @Test fun failedQuarantineDatabaseUpdateRemainsFatalAndPreservesPendingRow() {
        val root = temporary.newFolder()
        FrameStore(root, media, checkpoint = { if (it == "prepared") error("death") }).use {
            assertThrows(IllegalStateException::class.java) { it.prepare(request) }
        }
        SQLiteDatabase.openDatabase(File(root, "index.sqlite").path, null, 0).use { db ->
            db.execSQL(
                "CREATE TRIGGER reject_quarantine BEFORE UPDATE ON frames " +
                    "WHEN NEW.state=2 BEGIN SELECT RAISE(FAIL, 'synthetic_database_failure'); END",
            )
        }
        FrameStore(root, media).use {
            assertThrows(SQLiteException::class.java) { it.recover(40) }
            assertEquals(0L, it.summary().quarantinedCount)
        }
        SQLiteDatabase.openDatabase(File(root, "index.sqlite").path, null, SQLiteDatabase.OPEN_READONLY).use { db ->
            db.rawQuery("SELECT state FROM frames", null).use {
                assertTrue(it.moveToFirst())
                assertEquals(0, it.getInt(0))
            }
        }
    }

    @Test fun publishedOriginalNeverDeletedAfterFailureOrAbandon() {
        val root = temporary.newFolder()
        FrameStore(root, media).use { store ->
            val frame = store.prepare(request)
            frame.output.stream.write(jpeg)
            media.fault = "publish_after"
            assertThrows(Exception::class.java) { store.finish(frame, 30) }
            store.abandon(frame)
            assertFalse(media.items.getValue(frame.uri).pending)
        }
        media.fault = null
        FrameStore(root, media).use {
            it.recover(40)
            assertEquals(1L, it.summary().count)
        }
        assertEquals(1, media.items.size)
    }

    @Test fun externalMissingChangedInaccessibleAreNonblockingHistoricalStatuses() {
        val root = temporary.newFolder()
        FrameStore(root, media).use { store ->
            val uri = save(store)
            media.items.getValue(uri).bytes += 0
            store.reconcile()
            assertEquals(Availability.CHANGED, store.summary().last!!.availability)
            assertEquals(1L, store.summary().count)
            media.fault = "inspect"
            store.reconcile()
            assertEquals(Availability.INACCESSIBLE, store.summary().last!!.availability)
            media.fault = null
            media.items.remove(uri)
            store.reconcile(lastOnly = true)
            assertEquals(Availability.MISSING, store.summary().last!!.availability)
            save(store)
            assertEquals(2L, store.summary().count)
        }
    }

    @Test fun sameSizeExternalEditsAreExplicitlyNotRehashedByReconciliation() {
        FrameStore(temporary.newFolder(), media).use { store ->
            val uri = save(store)
            media.items.getValue(uri).bytes[4] = 0
            media.fault = "open_read"
            store.reconcile()
            assertEquals(Availability.AVAILABLE, store.summary().last!!.availability)
        }
    }

    @Test fun publicationAcknowledgedThenExternallyDeletedOrInaccessibleCommitsHistory() {
        for (deleted in listOf(false, true)) {
            val backend = FakeMediaDestination()
            backend.afterPublish = { uri -> if (deleted) backend.items.remove(uri) else backend.fault = "inspect" }
            FrameStore(temporary.newFolder(), backend).use { store ->
                save(store)
                assertEquals(1L, store.summary().count)
                assertEquals(if (deleted) Availability.MISSING else Availability.INACCESSIBLE, store.summary().last!!.availability)
                assertEquals(jpeg.size.toLong(), store.summary().last!!.bytes)
            }
        }
    }

    @Test fun trashAndRestoreChangeAvailabilityWithoutDeletingOrChangingHistoricalMetadata() {
        FrameStore(temporary.newFolder(), media).use { store ->
            val uri = save(store)
            media.items.getValue(uri).trashed = true
            store.reconcile(lastOnly = true)
            assertEquals(Availability.TRASHED, store.summary().last!!.availability)
            assertEquals(1L, store.summary().count)
            assertEquals(jpeg.size.toLong(), store.summary().last!!.bytes)
            media.items.getValue(uri).trashed = false
            store.reconcile(lastOnly = true)
            assertEquals(Availability.AVAILABLE, store.summary().last!!.availability)
            assertEquals(1, media.items.size)
        }
    }

    @Test fun lastViewChecksReadabilityWithoutRehashAndClosesInput() {
        FrameStore(temporary.newFolder(), media).use { store ->
            save(store)
            media.fault = "open_read"
            store.reconcile(lastOnly = true)
            assertEquals(Availability.INACCESSIBLE, store.summary().last!!.availability)
            media.fault = null
            store.reconcile(lastOnly = true)
            assertEquals(Availability.AVAILABLE, store.summary().last!!.availability)
            assertEquals(0, media.readsOpen)
        }
    }

    @Test fun externalMoveOrDeleteAfterPublicationBeforeCommitPreservesHistoricalMetadata() {
        for (deleted in listOf(false, true)) {
            val root = temporary.newFolder()
            val backend = FakeMediaDestination()
            FrameStore(root, backend, checkpoint = { if (it == "published") error("death") }).use {
                assertThrows(Exception::class.java) { save(it) }
            }
            if (deleted) {
                backend.items.clear()
            } else {
                backend.items.values.single().let {
                    it.identity = MediaIdentity(it.identity.name, "Pictures/Moved/")
                }
            }
            FrameStore(root, backend).use {
                it.recover(40)
                it.recover(50)
                assertEquals(1L, it.summary().count)
                assertEquals(if (deleted) Availability.MISSING else Availability.CHANGED, it.summary().last!!.availability)
            }
            assertEquals(if (deleted) 0 else 1, backend.items.size)
        }
    }

    @Test fun pendingFailureBlocksRecoveryRatherThanDestroyingEvidence() {
        val root = temporary.newFolder()
        FrameStore(root, media, checkpoint = { if (it == "validated") error("death") }).use { store ->
            assertThrows(Exception::class.java) { save(store) }
        }
        media.items.values
            .single()
            .bytes += 0
        FrameStore(root, media).use { store ->
            assertThrows(Exception::class.java) { store.recover(40) }
            assertEquals(0L, store.summary().count)
        }
        assertEquals(1, media.items.size)
        assertTrue(
            media.items.values
                .single()
                .pending,
        )
    }

    @Test fun recoveryDeletionFailureAndWrongOwnershipNeverDeleteOtherRows() {
        for (fault in listOf("delete", "find", "foreign")) {
            val root = temporary.newFolder()
            val backend = FakeMediaDestination()
            FrameStore(root, backend, checkpoint = { if (it == "output_opened") error("death") }).use {
                assertThrows(Exception::class.java) { it.prepare(request) }
            }
            val other = backend.insert(MediaIdentity("${UUID.randomUUID()}.jpg", "Pictures/Unrelated/"))
            if (fault ==
                "foreign"
            ) {
                backend.items.values
                    .first()
                    .owner = "other.app"
            } else {
                backend.fault = if (fault == "find") "inspect" else fault
            }
            FrameStore(root, backend).use { assertThrows(Exception::class.java) { it.recover(40) } }
            assertTrue(backend.items.containsKey(other))
            assertEquals(2, backend.items.size)
        }
    }

    @Test fun reserveAndInvalidJpegNeverPublish() {
        val root = temporary.newFolder()
        FrameStore(root, media, { FrameStore.RESERVE_BYTES - 1 }).use { assertThrows(Exception::class.java) { it.prepare(request) } }
        assertTrue(media.items.isEmpty())
        FrameStore(root, media).use { store ->
            for (bytes in listOf(
                byteArrayOf(),
                byteArrayOf(0, 0, 0, 0),
                byteArrayOf(-1, -40, 1, -1, -39),
                jpeg.dropLast(2).toByteArray(),
            )) {
                val frame = store.prepare(request)
                frame.output.stream.write(bytes)
                assertThrows(Exception::class.java) { store.finish(frame, 30) }
                store.abandon(frame)
            }
            assertTrue(media.items.isEmpty())
        }
    }

    @Test fun backwardsWallClockStillSelectsLastInsertedFrame() {
        FrameStore(temporary.newFolder(), media).use { store ->
            save(store, 1_000)
            save(store, 500)
            assertEquals(500L, store.summary().lastSavedMs)
            assertEquals(2L, store.summary().count)
        }
    }

    private fun legacyFixture(
        root: File,
        state: Int = 1,
    ): String {
        val id = UUID.randomUUID().toString()
        File(root, "$id.jpg").writeBytes(jpeg)
        SQLiteDatabase.openOrCreateDatabase(File(root, "index.sqlite"), null).use { db ->
            db.execSQL(
                "CREATE TABLE frames (id TEXT PRIMARY KEY, state INTEGER NOT NULL DEFAULT 0, " +
                    "request_wall_ms INTEGER NOT NULL, request_elapsed_ms INTEGER NOT NULL, interval_ms INTEGER NOT NULL, " +
                    "settings TEXT NOT NULL, cover_shadow TEXT NOT NULL, " +
                    "sha256 TEXT, bytes INTEGER, saved_wall_ms INTEGER, recovered INTEGER NOT NULL DEFAULT 0)",
            )
            db.execSQL(
                "INSERT INTO frames VALUES (?, ?, 10, 20, 2000, 'v1;legacy', 'SHADOW;true', 'legacy-hash', ?, 30, 0)",
                arrayOf<Any>(id, state, jpeg.size),
            )
            db.execSQL("CREATE TABLE sync_fixture (token TEXT)")
            db.execSQL("INSERT INTO sync_fixture VALUES ('preserved')")
            db.version = 1
        }
        return id
    }

    @Test fun transactionalV1MigrationPreservesPrivateJpegRowsAndOtherTables() {
        for (state in listOf(0, 1)) {
            val root = temporary.newFolder()
            val id = legacyFixture(root, state)
            FrameStore(root, media).use { store ->
                store.recover(40)
                store.recover(50)
                assertEquals(1L, store.summary().count)
                assertEquals(Availability.LEGACY_PRIVATE, store.summary().last!!.availability)
                assertNull(store.summary().last!!.width)
                assertNull(store.summary().last!!.uri)
            }
            assertArrayEquals(jpeg, File(root, "$id.jpg").readBytes())
            assertTrue(media.items.isEmpty())
            SQLiteDatabase.openDatabase(File(root, "index.sqlite").path, null, SQLiteDatabase.OPEN_READONLY).use { db ->
                assertEquals(2, db.version)
                db.rawQuery("SELECT token FROM sync_fixture", null).use {
                    assertTrue(it.moveToFirst())
                    assertEquals("preserved", it.getString(0))
                }
                db.rawQuery("SELECT settings, cover_shadow FROM frames", null).use {
                    assertTrue(it.moveToFirst())
                    assertEquals("v1;legacy", it.getString(0))
                    assertEquals("SHADOW;true", it.getString(1))
                }
            }
        }
    }

    @Test fun failedMigrationRollsBackSchemaAndVersion() {
        val root = temporary.newFolder()
        val id = legacyFixture(root)
        assertThrows(Exception::class.java) { FrameStore(root, media, checkpoint = { if (it == "migration") error("death") }) }
        SQLiteDatabase.openDatabase(File(root, "index.sqlite").path, null, SQLiteDatabase.OPEN_READONLY).use { db ->
            assertEquals(1, db.version)
            db.rawQuery("SELECT * FROM frames", null).use { assertEquals(-1, it.getColumnIndex("locator_kind")) }
        }
        assertArrayEquals(jpeg, File(root, "$id.jpg").readBytes())
        FrameStore(root, media).use { it.recover(40) }
    }

    @Test fun damagedOrUnindexedLegacyOriginalStillFailsWithoutDeletion() {
        val root = temporary.newFolder()
        val id = legacyFixture(root)
        File(root, "$id.jpg").appendBytes(byteArrayOf(0))
        FrameStore(root, media).use { assertThrows(Exception::class.java) { it.recover(40) } }
        assertTrue(File(root, "$id.jpg").exists())
        val orphanRoot = temporary.newFolder()
        File(orphanRoot, "orphan.jpg").writeBytes(jpeg)
        FrameStore(orphanRoot, media).use { assertThrows(Exception::class.java) { it.recover(40) } }
        assertArrayEquals(jpeg, File(orphanRoot, "orphan.jpg").readBytes())
    }

    @Test fun corruptionIsNotSilentlyDeleted() {
        val root = temporary.newFolder()
        val broken = ByteArray(100) { it.toByte() }
        File(root, "index.sqlite").writeBytes(broken)
        assertThrows(SQLiteException::class.java) { FrameStore(root, media) }
        assertArrayEquals(broken, File(root, "index.sqlite").readBytes())
    }

    @Test fun legacyScratchCleanupIsNarrowAndRecoveryCannotRaceLiveWriter() {
        val root = temporary.newFolder()
        val scratch = File(root, "CameraX${UUID.randomUUID()}.part").apply { writeBytes(byteArrayOf(1)) }
        val unrelated = File(root, "CameraXnotuuid.part").apply { writeBytes(byteArrayOf(2)) }
        val link = File(root, "CameraX${UUID.randomUUID()}.part").toPath()
        Files.createSymbolicLink(link, unrelated.toPath())
        FrameStore(root, media).use { store ->
            store.recover(20)
            assertFalse(scratch.exists())
            assertTrue(unrelated.exists())
            assertTrue(Files.isSymbolicLink(link))
            val frame = store.prepare(request)
            assertThrows(Exception::class.java) { store.recover(30) }
            assertEquals(1, media.writesOpen)
            store.abandon(frame)
        }
    }
}
