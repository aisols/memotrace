package org.memotrace.recorder

import android.database.sqlite.SQLiteDatabase
import android.os.BatteryManager
import android.util.JsonReader
import android.util.JsonToken
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
import org.memotrace.recorder.storage.CaptureAttemptStart
import org.memotrace.recorder.storage.DeviceSnapshot
import org.memotrace.recorder.storage.FrameRequest
import org.memotrace.recorder.storage.FrameStore
import org.memotrace.recorder.storage.LongRunReportWriter
import org.memotrace.recorder.storage.SessionStart
import org.memotrace.recorder.storage.TelemetrySample
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode
import org.robolectric.shadows.ShadowStatFs
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.io.File
import java.io.StringReader
import java.util.UUID
import java.util.zip.ZipInputStream

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [36], application = android.app.Application::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
class SessionJournalTest {
    @get:Rule val temporary = TemporaryFolder()
    private val media = FakeMediaDestination()
    private val device = DeviceSnapshot("Maker", "Model", "16", 36, "BUILD", "0.3.0", 3)

    @Before fun freeDisk() {
        ShadowStatFs.registerStats(temporary.root.path, 1_000_000, 500_000, 500_000)
    }

    private fun sessionStart(
        id: String = UUID.randomUUID().toString(),
        settings: String = "rear;mode=minimizeLatency",
        device: DeviceSnapshot = this.device,
    ) = SessionStart(id, CaptureProfile.WIDE_90.id, 1920, 1080, 90, settings, 1_000, 100, device)

    private fun sample(
        reason: String,
        elapsed: Long,
        level: Int? = null,
        temperature: Int? = null,
        thermal: Int? = null,
        scale: Int? = level?.let { 100 },
        status: Int? = level?.let { BatteryManager.BATTERY_STATUS_DISCHARGING },
        plugged: Int? = level?.let { 0 },
        publicFree: Long? = null,
        privateFree: Long? = null,
    ) = TelemetrySample(
        1_000 + elapsed,
        elapsed,
        reason,
        level,
        scale,
        if (level != null && scale != null && scale > 0 && level in 0..scale) level * 100.0 / scale else null,
        status,
        plugged,
        temperature,
        null,
        null,
        null,
        null,
        thermal,
        publicFree,
        privateFree,
    )

    @Test fun schemaV2MigrationAddsJournalWithoutChangingFramesOrUnrelatedTables() {
        val root = temporary.newFolder()
        val captureSession = CaptureSession(CaptureProfile.WIDE_90, 1_000)
        FrameStore(root, media).use { store ->
            val frame =
                store.prepare(FrameRequest(1_000, 100, 2_000, "historical-v2", "SHADOW;unknown", captureSession, 16, 12))
            frame.output.stream.write(syntheticJpeg())
            store.finish(frame, 2_000)
        }
        SQLiteDatabase.openDatabase(File(root, "index.sqlite").path, null, 0).use { db ->
            db.execSQL("DROP TABLE capture_attempts")
            db.execSQL("DROP TABLE telemetry_samples")
            db.execSQL("DROP TABLE capture_sessions")
            db.execSQL("CREATE TABLE unrelated_v2 (value TEXT)")
            db.execSQL("INSERT INTO unrelated_v2 VALUES ('kept')")
            db.version = 2
        }
        FrameStore(root, media).close()
        SQLiteDatabase.openDatabase(File(root, "index.sqlite").path, null, SQLiteDatabase.OPEN_READONLY).use { db ->
            assertEquals(4, db.version)
            for (table in listOf("capture_sessions", "telemetry_samples", "capture_attempts")) {
                db.rawQuery("SELECT COUNT(*) FROM $table", null).use {
                    assertTrue(it.moveToFirst())
                    assertEquals(0, it.getInt(0))
                }
            }
            db.rawQuery("SELECT value FROM unrelated_v2", null).use {
                assertTrue(it.moveToFirst())
                assertEquals("kept", it.getString(0))
            }
            db.rawQuery("SELECT settings, state FROM frames", null).use {
                assertTrue(it.moveToFirst())
                assertEquals("historical-v2", it.getString(0))
                assertEquals(1, it.getInt(1))
                assertFalse(it.moveToNext())
            }
        }
    }

    @Test fun schemaV3MigrationAddsDueAndRecoveryDetectionWithoutChangingRows() {
        val root = temporary.newFolder()
        val session = sessionStart()
        FrameStore(root, media).use { store ->
            store.startCaptureSession(session, sample("START", 100))
            store.beginCaptureAttempt(CaptureAttemptStart(UUID.randomUUID().toString(), session.id, 2_000, 200, 2_000))
        }
        SQLiteDatabase.openDatabase(File(root, "index.sqlite").path, null, 0).use { db ->
            db.execSQL("ALTER TABLE capture_sessions DROP COLUMN recovery_detected_wall_ms")
            db.execSQL("ALTER TABLE capture_attempts DROP COLUMN scheduled_due_elapsed_ms")
            db.execSQL(
                "ALTER TABLE capture_attempts RENAME COLUMN camera_invoke_ready_elapsed_ms TO camera_submit_elapsed_ms",
            )
            db.version = 3
        }
        FrameStore(root, media).use { store ->
            store.recover(4_000)
            assertEquals(1, store.recoverOpenSessions(5_000))
            val report = store.report(session.id)!!
            assertEquals(5_000L, report.session.recoveryDetectedWallMs)
            assertNull(report.captures.single().scheduledDueElapsedMs)
        }
    }

    @Test fun schemaV3MigrationFailureRollsBackColumnsRowsAndVersion() {
        val root = temporary.newFolder()
        val session = sessionStart()
        val attempt = CaptureAttemptStart(UUID.randomUUID().toString(), session.id, 2_000, 200, 2_000)
        FrameStore(root, media).use { store ->
            store.startCaptureSession(session, sample("START", 100))
            store.beginCaptureAttempt(attempt)
        }
        SQLiteDatabase.openDatabase(File(root, "index.sqlite").path, null, 0).use { db ->
            db.execSQL("ALTER TABLE capture_sessions DROP COLUMN recovery_detected_wall_ms")
            db.execSQL("ALTER TABLE capture_attempts DROP COLUMN scheduled_due_elapsed_ms")
            db.execSQL("ALTER TABLE capture_attempts RENAME COLUMN camera_invoke_ready_elapsed_ms TO camera_submit_elapsed_ms")
            db.version = 3
        }

        assertThrows(IllegalStateException::class.java) {
            FrameStore(root, media, checkpoint = { if (it == "migration") error("synthetic_migration_failure") })
        }

        SQLiteDatabase.openDatabase(File(root, "index.sqlite").path, null, SQLiteDatabase.OPEN_READONLY).use { db ->
            assertEquals(3, db.version)
            db.rawQuery("SELECT * FROM capture_sessions", null).use { rows ->
                assertEquals(-1, rows.getColumnIndex("recovery_detected_wall_ms"))
                assertTrue(rows.moveToFirst())
                assertEquals(session.id, rows.getString(rows.getColumnIndexOrThrow("id")))
            }
            db.rawQuery("SELECT * FROM capture_attempts", null).use { rows ->
                assertEquals(-1, rows.getColumnIndex("scheduled_due_elapsed_ms"))
                assertTrue(rows.getColumnIndex("camera_submit_elapsed_ms") >= 0)
                assertEquals(-1, rows.getColumnIndex("camera_invoke_ready_elapsed_ms"))
                assertTrue(rows.moveToFirst())
                assertEquals(attempt.id, rows.getString(rows.getColumnIndexOrThrow("attempt_id")))
                assertEquals("PENDING", rows.getString(rows.getColumnIndexOrThrow("result")))
            }
        }
    }

    @Test fun openingExistingSchemaV4LeavesRowsUnchanged() {
        val root = temporary.newFolder()
        val session = sessionStart()
        val attempt = CaptureAttemptStart(UUID.randomUUID().toString(), session.id, 2_000, 200, 2_000, 190)
        FrameStore(root, media).use { store ->
            store.startCaptureSession(session, sample("START", 100))
            store.beginCaptureAttempt(attempt)
        }

        FrameStore(root, media).close()

        SQLiteDatabase.openDatabase(File(root, "index.sqlite").path, null, SQLiteDatabase.OPEN_READONLY).use { db ->
            assertEquals(4, db.version)
            db.rawQuery("SELECT id, completion_status, start_wall_ms FROM capture_sessions", null).use { rows ->
                assertTrue(rows.moveToFirst())
                assertEquals(session.id, rows.getString(0))
                assertEquals("OPEN", rows.getString(1))
                assertEquals(session.startWallMs, rows.getLong(2))
                assertFalse(rows.moveToNext())
            }
            db
                .rawQuery(
                    "SELECT attempt_id, scheduled_due_elapsed_ms, result FROM capture_attempts",
                    null,
                ).use { rows ->
                    assertTrue(rows.moveToFirst())
                    assertEquals(attempt.id, rows.getString(0))
                    assertEquals(190L, rows.getLong(1))
                    assertEquals("PENDING", rows.getString(2))
                    assertFalse(rows.moveToNext())
                }
        }
    }

    @Test fun openSessionRecoveryRetainsEmptySessionAndMarksInterrupted() {
        val root = temporary.newFolder()
        val session = sessionStart()
        FrameStore(root, media).use {
            it.startCaptureSession(session, sample("START", 100))
            it.beginCaptureAttempt(CaptureAttemptStart(UUID.randomUUID().toString(), session.id, 2_000, 200, 2_000))
        }
        FrameStore(root, media).use { store ->
            assertThrows(IllegalStateException::class.java) { store.recoverOpenSessions(5_000) }
            store.recover(4_000)
            assertEquals(1, store.recoverOpenSessions(5_000))
            assertEquals(0, store.recoverOpenSessions(6_000))
            val report = store.report(session.id)!!
            assertEquals("INTERRUPTED", report.session.completionStatus)
            assertEquals("PROCESS_INTERRUPTED", report.session.terminalReason)
            assertEquals(1, report.captures.size)
            assertEquals("INTERRUPTED", report.captures.single().result)
            assertEquals("PROCESS_INTERRUPTED", report.captures.single().failurePhase)
            assertNull(report.captures.single().commitCompleteElapsedMs)
            assertNull(report.session.endWallMs)
            assertNull(report.session.endElapsedMs)
            assertEquals(5_000L, report.session.recoveryDetectedWallMs)
            assertEquals(1, report.samples.size)
            assertEquals(0L, store.summary(session.id).sessionCount)
            val output = ByteArrayOutputStream()
            LongRunReportWriter.write(report, output)
            var sessionsCsv = ""
            ZipInputStream(ByteArrayInputStream(output.toByteArray())).use { zip ->
                while (true) {
                    val entry = zip.nextEntry ?: break
                    if (entry.name == "sessions.csv") sessionsCsv = zip.readBytes().toString(Charsets.UTF_8)
                }
            }
            assertTrue(sessionsCsv.contains(",90,0,,true,PROCESS_INTERRUPTED,INTERRUPTED,"))
            assertFalse(sessionsCsv.contains("5000"))
        }
    }

    @Test fun recoveryNeverUsesLowerOrHigherNextProcessUptimeForElapsedFacts() {
        for (newUptime in listOf(50L, 50_000L)) {
            val root = temporary.newFolder()
            val session = sessionStart()
            FrameStore(root, media).use {
                it.startCaptureSession(session, sample("START", 100))
            }
            FrameStore(root, media).use { store ->
                store.recover(4_000)
                assertEquals(1, store.recoverOpenSessions(5_000))
                val report = store.report(session.id)!!
                assertNull(report.session.endElapsedMs)
                val diagnostics = store.diagnostics(session.id, newUptime)!!
                assertNull(diagnostics.durationMs)
                assertNull(diagnostics.sampleAgeMs)
                assertNull(diagnostics.pipelineLatency)
                assertNull(diagnostics.saveLatency)
            }
        }
    }

    @Test fun recoveryClassifiesAlreadyCommittedPendingAttemptAsSavedWithoutCommitTime() {
        val root = temporary.newFolder()
        val session = sessionStart()
        val attempt = CaptureAttemptStart(UUID.randomUUID().toString(), session.id, 2_000, 200, 2_000, 200)
        FrameStore(root, media).use { store ->
            store.startCaptureSession(session, sample("START", 100))
            store.beginCaptureAttempt(attempt)
            val captureSession = CaptureSession(CaptureProfile.WIDE_90, 1_000, session.id)
            val frame = store.prepare(FrameRequest(2_000, 200, 2_000, "settings", "SHADOW", captureSession, 16, 12))
            store.markCameraInvokeReady(attempt.id, frame.id, 210, 220)
            store.markCameraCompleted(attempt.id, 230, 240)
            frame.output.stream.write(syntheticJpeg())
            store.finish(frame, 3_000)
        }
        FrameStore(root, media).use { store ->
            store.recover(4_000)
            assertEquals(1, store.recoverOpenSessions(5_000))
            val capture = store.report(session.id)!!.captures.single()
            assertEquals("SAVED", capture.result)
            assertEquals("RECOVERY_FRAME_COMMITTED", capture.failurePhase)
            assertNull(capture.commitCompleteElapsedMs)
            assertEquals(1L, store.summary(session.id).sessionCount)
        }
    }

    @Test fun frameRecoveryRunsBeforePendingAttemptClassification() {
        val root = temporary.newFolder()
        val session = sessionStart()
        val attempt = CaptureAttemptStart(UUID.randomUUID().toString(), session.id, 2_000, 200, 2_000, 200)
        FrameStore(root, media, checkpoint = { if (it == "published") error("process_death") }).use { store ->
            store.startCaptureSession(session, sample("START", 100))
            store.beginCaptureAttempt(attempt)
            val captureSession = CaptureSession(CaptureProfile.WIDE_90, 1_000, session.id)
            val frame = store.prepare(FrameRequest(2_000, 200, 2_000, "settings", "SHADOW", captureSession, 16, 12))
            store.markCameraInvokeReady(attempt.id, frame.id, 210, 220)
            store.markCameraCompleted(attempt.id, 230, 240)
            frame.output.stream.write(syntheticJpeg())
            assertThrows(IllegalStateException::class.java) { store.finish(frame, 3_000) }
        }
        FrameStore(root, media).use { store ->
            store.recover(4_000)
            assertEquals(1, store.recoverOpenSessions(5_000))
            val capture = store.report(session.id)!!.captures.single()
            assertEquals("SAVED", capture.result)
            assertEquals("RECOVERY_FRAME_COMMITTED", capture.failurePhase)
            assertNull(capture.commitCompleteElapsedMs)
            assertEquals(1L, store.summary(session.id).sessionCount)
        }
    }

    @Test fun terminalSessionPendingAttemptWithoutRecoverableFrameBecomesInterrupted() {
        val root = temporary.newFolder()
        val session = sessionStart()
        val attempt = CaptureAttemptStart(UUID.randomUUID().toString(), session.id, 2_000, 200, 2_000, 200)
        FrameStore(root, media).use { store ->
            store.startCaptureSession(session, sample("START", 100))
            val frame =
                store.prepareCapture(
                    attempt,
                    FrameRequest(
                        2_000,
                        200,
                        2_000,
                        "settings",
                        "SHADOW",
                        CaptureSession(CaptureProfile.WIDE_90, 1_000, session.id),
                        16,
                        12,
                    ),
                )
            store.markCameraInvokeReady(attempt.id, frame.id, 210, 220)
            store.markCameraCompleted(attempt.id, 230, 240)
            frame.output.stream.write(syntheticJpeg())
            frame.output.close()
            store.endCaptureSession(session.id, 3_000, 300, "STORAGE_FAILURE", "FAILED", sample("END", 300))
        }

        FrameStore(root, media).use { store ->
            store.recover(4_000)
            assertEquals(0, store.recoverOpenSessions(5_000))
            val capture = store.report(session.id)!!.captures.single()
            assertEquals("INTERRUPTED", capture.result)
            assertEquals("PROCESS_INTERRUPTED", capture.failurePhase)
            assertNull(capture.commitCompleteElapsedMs)
            assertEquals(0L, store.summary(session.id).count)
            assertEquals(0, media.writesOpen)
            assertTrue(media.items.isEmpty())
        }
    }

    @Test fun startPeriodicAndEndSamplesAllowUnavailableBatteryProperties() {
        val root = temporary.newFolder()
        val session = sessionStart()
        FrameStore(root, media).use { store ->
            store.startCaptureSession(session, sample("START", 100))
            store.addTelemetrySample(session.id, sample("PERIODIC", 60_100))
            store.endCaptureSession(session.id, 122_000, 120_100, "USER_PAUSE", "COMPLETE", sample("END", 120_100))
            val report = store.report(session.id)!!
            assertEquals(listOf("START", "PERIODIC", "END"), report.samples.map { it.sample.reason })
            assertTrue(report.samples.all { it.sample.batteryLevel == null && it.sample.currentNowUa == null })
            assertEquals("COMPLETE", report.session.completionStatus)
            val diagnostics = store.diagnostics(session.id, 500_000)!!
            assertEquals(3, diagnostics.sampleCount)
            assertEquals(0L, diagnostics.sampleAgeMs)
        }
    }

    @Test fun attemptsRetainOrderedPhasesAndTypedFailedOutcomes() {
        FrameStore(temporary.newFolder(), media).use { store ->
            val session = sessionStart()
            store.startCaptureSession(session, sample("START", 100))
            val camera = CaptureAttemptStart(UUID.randomUUID().toString(), session.id, 2_000, 200, 2_000)
            store.beginCaptureAttempt(camera)
            store.markCameraInvokeReady(camera.id, UUID.randomUUID().toString(), 210, 220)
            store.markCameraCompleted(camera.id, 230, 240)
            store.finishCaptureAttempt(camera.id, 250, "CAMERA_FAILURE", "CAMERAX_TERMINAL")
            val prepare = CaptureAttemptStart(UUID.randomUUID().toString(), session.id, 3_000, 300, 2_000)
            store.beginCaptureAttempt(prepare)
            store.finishCaptureAttempt(prepare.id, 310, "STORAGE_FAILURE", "PREPARE")
            val invalid = CaptureAttemptStart(UUID.randomUUID().toString(), session.id, 5_000, 500, 2_000)
            store.beginCaptureAttempt(invalid)
            assertThrows(IllegalStateException::class.java) {
                store.markCameraInvokeReady(invalid.id, UUID.randomUUID().toString(), 499, 500)
            }
            store.finishCaptureAttempt(invalid.id, 500, "STORAGE_FAILURE", "PREPARE")
            store.endCaptureSession(session.id, 6_000, 600, "USER_PAUSE", "COMPLETE", sample("END", 600))
            val captures = store.report(session.id)!!
            assertEquals(listOf("CAMERA_FAILURE", "STORAGE_FAILURE", "STORAGE_FAILURE"), captures.captures.map { it.result })
            val first = captures.captures.first()
            assertTrue(
                listOfNotNull(
                    first.requestElapsedMs,
                    first.prepareCompleteElapsedMs,
                    first.cameraInvokeReadyElapsedMs,
                    first.cameraTerminalElapsedMs,
                    first.diskDrainedElapsedMs,
                    first.commitCompleteElapsedMs,
                ).zipWithNext().all { (left, right) -> left <= right },
            )
            assertNull(captures.captures.last().frameId)
        }
    }

    @Test fun successfulCaptureUsesSixOrderedDatabaseDurabilityOperations() {
        val databaseOperations = mutableListOf<String>()
        val session = sessionStart().copy(startElapsedMs = 0)
        val attempt = CaptureAttemptStart(UUID.randomUUID().toString(), session.id, 2_000, 0, 2_000, 0)
        FrameStore(
            temporary.newFolder(),
            media,
            checkpoint = { if (it.startsWith("db_")) databaseOperations += it },
        ).use { store ->
            store.startCaptureSession(session, sample("START", 0))
            val frame =
                store.prepareCapture(
                    attempt,
                    FrameRequest(
                        2_000,
                        0,
                        2_000,
                        "settings",
                        "SHADOW;unknown",
                        CaptureSession(CaptureProfile.WIDE_90, 1_000, session.id),
                        16,
                        12,
                    ),
                )
            store.markCameraInvokeReady(attempt.id, frame.id, 0, 0)
            store.markCameraCompleted(attempt.id, 0, 0)
            frame.output.stream.write(syntheticJpeg())
            store.finishCapture(frame, attempt.id, 3_000, null)
            assertEquals(1, store.diagnostics(session.id, 0)!!.successCount)
        }
        assertEquals(
            listOf(
                "db_attempt_frame",
                "db_uri",
                "db_pre_camera",
                "db_camera_completed",
                "db_validated",
                "db_frame_attempt_commit",
            ),
            databaseOperations,
        )
    }

    @Test fun diagnosticsAggregatePercentilesGapsOverrunsBatterySizesAndBytes() {
        val root = temporary.newFolder()
        val start = sessionStart()
        val captureSession = CaptureSession(CaptureProfile.WIDE_90, 1_000, start.id)
        FrameStore(root, media).use { store ->
            store.startCaptureSession(start, sample("START", 100, 80, 310, 0, publicFree = 1_000, privateFree = 900))
            val requests = listOf(1_000L, 2_000L, 5_000L, 7_000L)
            val due = listOf(1_000L, 2_000L, 4_000L, 7_000L)
            val latencies = listOf(100L, 200L, 300L, 400L)
            requests.zip(latencies).forEachIndexed { index, (requestElapsed, latency) ->
                val attempt =
                    CaptureAttemptStart(
                        UUID.randomUUID().toString(),
                        start.id,
                        10_000 + requestElapsed,
                        requestElapsed,
                        if (index == 3) 2_000 else 1_000,
                        due[index],
                    )
                val frame =
                    store.prepareCapture(
                        attempt,
                        FrameRequest(
                            10_000 + requestElapsed,
                            requestElapsed,
                            if (index == 3) 2_000 else 1_000,
                            "settings",
                            "SHADOW;unknown",
                            captureSession,
                            1920,
                            1080,
                        ),
                    )
                store.markCameraInvokeReady(attempt.id, frame.id, requestElapsed + 10, requestElapsed + 20)
                store.markCameraCompleted(attempt.id, requestElapsed + 30, requestElapsed + 40)
                frame.output.stream.write(syntheticJpeg())
                store.finish(frame, 20_000L + index)
                store.finishCaptureAttempt(attempt.id, requestElapsed + latency, "SAVED", null)
            }
            store.addTelemetrySample(start.id, sample("PERIODIC", 6_000, 79, 350, 3, publicFree = 800, privateFree = 700))
            store.endCaptureSession(
                start.id,
                20_000,
                8_000,
                "USER_PAUSE",
                "COMPLETE",
                sample("END", 8_000, 78, 330, 2, publicFree = 900, privateFree = 600),
            )
            val result = store.diagnostics(start.id, 8_000)!!
            assertEquals(4, result.successCount)
            assertEquals(4L, result.frameCount)
            assertEquals(4L * syntheticJpeg().size, result.frameBytes)
            assertEquals(listOf(2_000L, 3_000L, 3_000L), listOf(result.requestGaps!!.p50, result.requestGaps.p95, result.requestGaps.max))
            assertEquals(1, result.overrunCount)
            assertEquals(1_000L, result.overrunMaxMs)
            assertEquals(
                listOf(200L, 400L, 400L),
                listOf(result.pipelineLatency!!.p50, result.pipelineLatency.p95, result.pipelineLatency.max),
            )
            assertEquals(listOf(160L, 360L, 360L), listOf(result.saveLatency!!.p50, result.saveLatency.p95, result.saveLatency.max))
            assertEquals(-2.0, result.batteryDeltaPercent!!, 0.0)
            assertEquals(310, result.temperatureMinTenthsC)
            assertEquals(350, result.temperatureMaxTenthsC)
            assertEquals(3, result.maxThermalStatus)
            assertEquals("16x12 (4)", result.actualSizes)
            assertEquals(1_000L, result.publicStorageStartBytes)
            assertEquals(900L, result.publicStorageEndBytes)
            assertEquals(800L, result.publicStorageMinimumBytes)
            assertEquals(900L, result.privateStorageStartBytes)
            assertEquals(600L, result.privateStorageEndBytes)
            assertEquals(600L, result.privateStorageMinimumBytes)
        }
    }

    @Test fun batteryDeltaRequiresActualEndpointsAndConsistentUnpluggedDischarge() {
        fun diagnostics(samples: List<TelemetrySample>) =
            FrameStore(temporary.newFolder(), FakeMediaDestination()).use { store ->
                val session = sessionStart()
                store.startCaptureSession(session, samples.first())
                samples.drop(1).dropLast(1).forEach { store.addTelemetrySample(session.id, it) }
                store.endCaptureSession(session.id, 10_000, 1_000, "USER_PAUSE", "COMPLETE", samples.last())
                store.diagnostics(session.id, 1_000)!!
            }

        diagnostics(listOf(sample("START", 100), sample("PERIODIC", 500, 80), sample("END", 1_000))).let {
            assertNull(it.batteryStartPercent)
            assertNull(it.batteryEndPercent)
            assertNull(it.batteryDeltaPercent)
        }
        diagnostics(
            listOf(
                sample("START", 100, 80),
                sample("PERIODIC", 500, 79, status = BatteryManager.BATTERY_STATUS_CHARGING, plugged = 1),
                sample("END", 1_000, 78),
            ),
        ).let {
            assertEquals(80.0, it.batteryStartPercent!!, 0.0)
            assertEquals(78.0, it.batteryEndPercent!!, 0.0)
            assertNull(it.batteryDeltaPercent)
        }
        diagnostics(listOf(sample("START", 100, 80), sample("PERIODIC", 500, 79), sample("END", 1_000, 78))).let {
            assertEquals(-2.0, it.batteryDeltaPercent!!, 0.0)
        }
    }

    @Test fun zipExportHasStableSchemaEscapingAndNoMediaOrPersonalFields() {
        FrameStore(temporary.newFolder(), media).use { store ->
            val escapedDevice = DeviceSnapshot("Maker", "Model,\"quoted\"\nline", "16", 36, "BUILD", "0.3.0", 3)
            val privateSetting = "private-${UUID.randomUUID()}"
            val startWallMs = 1_700_000_123_456L
            val startElapsedMs = 900_000L
            val requestWallMs = 1_700_000_123_506L
            val session =
                sessionStart(settings = privateSetting, device = escapedDevice).copy(
                    startWallMs = startWallMs,
                    startElapsedMs = startElapsedMs,
                )
            store.startCaptureSession(session, sample("START", startElapsedMs))
            val attempt =
                CaptureAttemptStart(
                    UUID.randomUUID().toString(),
                    session.id,
                    requestWallMs,
                    startElapsedMs + 50,
                    2_000,
                    startElapsedMs + 40,
                )
            val frame =
                store.prepareCapture(
                    attempt,
                    FrameRequest(
                        requestWallMs,
                        startElapsedMs + 50,
                        2_000,
                        "capture-settings",
                        "SHADOW;unknown",
                        CaptureSession(CaptureProfile.WIDE_90, 1_000, session.id),
                        16,
                        12,
                    ),
                )
            store.markCameraInvokeReady(attempt.id, frame.id, startElapsedMs + 60, startElapsedMs + 70)
            store.markCameraCompleted(attempt.id, startElapsedMs + 80, startElapsedMs + 90)
            frame.output.stream.write(syntheticJpeg())
            store.finish(frame, 1_700_000_123_556L)
            store.finishCaptureAttempt(attempt.id, startElapsedMs + 100, "SAVED", null)
            store.endCaptureSession(
                session.id,
                1_700_000_123_556L,
                startElapsedMs + 100,
                "USER_PAUSE",
                "COMPLETE",
                sample("END", startElapsedMs + 100),
            )
            val report = store.report(session.id)!!
            val output = ByteArrayOutputStream()
            val repeated = ByteArrayOutputStream()
            LongRunReportWriter.write(report, output)
            LongRunReportWriter.write(report, repeated)
            assertTrue(output.toByteArray().contentEquals(repeated.toByteArray()))
            val entries = linkedMapOf<String, String>()
            ZipInputStream(ByteArrayInputStream(output.toByteArray())).use { zip ->
                while (true) {
                    val entry = zip.nextEntry ?: break
                    entries[entry.name] = zip.readBytes().toString(Charsets.UTF_8)
                }
            }
            assertEquals(listOf("manifest.json", "sessions.csv", "samples.csv", "captures.csv"), entries.keys.toList())
            val manifest = linkedMapOf<String, String>()
            JsonReader(StringReader(entries.getValue("manifest.json"))).use { reader ->
                reader.beginObject()
                while (reader.hasNext()) manifest[reader.nextName()] = reader.nextString()
                reader.endObject()
                assertEquals(JsonToken.END_DOCUMENT, reader.peek())
            }
            assertEquals(LongRunReportWriter.SCHEMA, manifest["schema"])
            assertEquals("1", manifest["session_ordinal"])
            assertTrue(entries.getValue("sessions.csv").contains("\"Model,\"\"quoted\"\"\nline\""))
            assertTrue(entries.getValue("sessions.csv").contains("start_offset_ms,end_offset_ms,recovery_detected"))
            assertTrue(entries.getValue("sessions.csv").contains(",0,100,false,"))
            assertTrue(entries.getValue("samples.csv").contains("sample_offset_ms"))
            assertTrue(entries.getValue("captures.csv").contains(",50,40,2000,60,70,80,90,100,SAVED,"))
            val lower = entries.values.joinToString("\n").lowercase()
            for (identifier in listOf(
                session.id,
                attempt.id,
                frame.id,
                frame.identity.name,
                frame.identity.path,
                frame.uri,
                privateSetting,
            )) {
                assertFalse(identifier, lower.contains(identifier.lowercase()))
            }
            for (forbidden in listOf(
                "session_id",
                "attempt_id",
                "sha256",
                "content://",
                "relative_path",
                ".jpg",
                "jpeg_bytes",
                "fingerprint",
                "android_id",
                "imei",
                "serial",
                "phone_number",
                "start_wall_ms",
                "start_elapsed_ms",
                "end_wall_ms",
                "end_elapsed_ms",
                "recovery_detected_wall_ms",
                "request_wall_ms",
                "request_elapsed_ms",
            )) {
                assertFalse(forbidden, lower.contains(forbidden))
            }
            for (absoluteTime in listOf(startWallMs, startElapsedMs, requestWallMs, startElapsedMs + 50)) {
                assertFalse(absoluteTime.toString(), lower.contains(absoluteTime.toString()))
            }
        }
    }
}
