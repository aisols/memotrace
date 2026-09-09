package org.memotrace.recorder

import android.annotation.SuppressLint
import android.content.ContentProviderOperation
import android.content.Context
import android.os.Bundle
import android.provider.MediaStore
import androidx.core.net.toUri
import androidx.test.platform.app.InstrumentationRegistry
import org.memotrace.recorder.storage.AndroidMediaDestination
import org.memotrace.recorder.storage.MediaDestination
import org.memotrace.recorder.storage.MediaIdentity
import org.memotrace.recorder.storage.UnlinkStatus
import org.memotrace.recorder.storage.UnlinkUnprovenException
import org.memotrace.recorder.storage.UnlinkWitness
import java.util.UUID

class CleanupResidue(
    val ledger: String,
    val uri: String?,
    val name: String,
    val status: UnlinkStatus,
) {
    val description get() = "Cleanup NOT proven: $ledger; $name; uri=$uri; status=$status; provenance retained"
}

/** Private per-run creation ledger, NOT a public subtree ownership assumption. */
class TestMediaNamespace(
    private val context: Context,
    val id: String = UUID.randomUUID().toString(),
    val prefix: String = "Pictures/MemoTrace-instrumentation/$id/",
    private val afterInsert: () -> Unit = {},
) {
    init {
        check(UUID.fromString(id).toString() == id)
        val pathId = prefix.removePrefix("Pictures/MemoTrace-instrumentation/").removeSuffix("/")
        check(prefix == "Pictures/MemoTrace-instrumentation/${UUID.fromString(pathId)}/")
    }

    private val ledgerName = "media-fixtures-$id"
    private val ledger = context.getSharedPreferences(ledgerName, Context.MODE_PRIVATE)
    private val backend = AndroidMediaDestination(context, prefix)
    private val witnesses = mutableMapOf<String, UnlinkWitness>()

    /** Only explicitly registered fixtures, held across a bounded test race and closed by cleanup. */
    fun retainUnlinkWitness(uri: String): UnlinkWitness {
        check(ledger.all.any { it.key.startsWith("uri:") && it.value == uri })
        return witnesses.getOrPut(uri) { backend.watchUnlink(uri) }
    }

    fun hasProvenance() = ledger.all.keys.any { it.startsWith("path:") }

    fun hasFixture(name: String) = ledger.contains("path:$name")

    fun closeWitnesses() {
        val failures = witnesses.values.mapNotNull { runCatching { it.close() }.exceptionOrNull() }
        witnesses.clear()
        if (failures.isNotEmpty()) {
            failures.drop(1).forEach { failures.first().addSuppressed(it) }
            throw failures.first()
        }
    }

    val destination =
        object : MediaDestination by backend {
            // Boolean commit failure matters: record provenance durably BEFORE asking the provider.
            @SuppressLint("UseKtx")
            override fun insert(identity: MediaIdentity): String {
                check(identity.path.startsWith(prefix))
                check(UUID.fromString(identity.name.removeSuffix(".jpg")).toString() + ".jpg" == identity.name)
                check(!ledger.contains("path:${identity.name}"))
                check(ledger.edit().putString("path:${identity.name}", identity.path).commit())
                val uri = backend.insert(identity)
                afterInsert()
                check(ledger.edit().putString("uri:${identity.name}", uri).commit())
                return uri
            }
        }

    @SuppressLint("UseKtx")
    fun cleanup(): List<CleanupResidue> {
        val retained = mutableListOf<CleanupResidue>()
        try {
            for (key in ledger.all.keys.filter { it.startsWith("path:") }) {
                val name = key.removePrefix("path:")
                val identity = MediaIdentity(name, checkNotNull(ledger.getString(key, null)))
                val uri = ledger.getString("uri:$name", null)
                val status =
                    try {
                        val entry =
                            if (uri != null) {
                                backend.inspect(uri)
                            } else {
                                // Lost insert response: only this pre-registered exact identity, never a subtree scan.
                                val matches = backend.find(identity)
                                check(matches.size == 1) { "fixture_insert_uncertain_keep_ledger" }
                                matches.single()
                            }
                        if (entry != null) {
                            check(uri == null || uri == entry.uri) { "fixture_uri_changed_keep_ledger" }
                            check(entry.owner == backend.owner && entry.path == identity.path && entry.name == identity.name) {
                                "fixture_identity_changed_keep_ledger"
                            }
                        }
                        val witness =
                            uri?.let { witnesses[it] } ?: entry?.let {
                                backend.watchUnlink(it.uri).also { proof -> witnesses[it.uri] = proof }
                            } ?: throw UnlinkUnprovenException("$ledgerName: missing row is not unlink proof for $name")
                        if (entry != null) {
                            val selection = "owner_package_name=? AND relative_path=? AND _display_name=?"
                            val args = arrayOf(context.packageName, identity.path, identity.name)
                            context.contentResolver.applyBatch(
                                MediaStore.AUTHORITY,
                                arrayListOf(
                                    ContentProviderOperation
                                        .newAssertQuery(entry.uri.toUri())
                                        .withSelection(selection, args)
                                        .withExpectedCount(1)
                                        .withYieldAllowed(false)
                                        .withExceptionAllowed(false)
                                        .build(),
                                    ContentProviderOperation
                                        .newDelete(entry.uri.toUri())
                                        .withSelection(selection, args)
                                        .withExpectedCount(1)
                                        .withYieldAllowed(false)
                                        .withExceptionAllowed(false)
                                        .build(),
                                ),
                            )
                        }
                        witness.status()
                    } catch (uncertain: UnlinkUnprovenException) {
                        uncertain.status
                    }
                if (status != UnlinkStatus.PROVEN_UNLINKED) {
                    val residue = CleanupResidue(ledgerName, uri, name, status)
                    retained.add(residue)
                    android.util.Log.w("MemoTraceTest", residue.description)
                    InstrumentationRegistry.getInstrumentation().sendStatus(
                        0,
                        Bundle().apply {
                            putString("stream", residue.description + "\n")
                        },
                    )
                    continue
                }
                check(
                    ledger
                        .edit()
                        .remove(key)
                        .remove("uri:$name")
                        .commit(),
                )
            }
            if (retained.isEmpty()) check(context.deleteSharedPreferences(ledgerName))
            return retained
        } finally {
            closeWitnesses()
        }
    }
}
