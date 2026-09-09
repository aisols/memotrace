package org.memotrace.recorder

import android.graphics.Bitmap
import org.memotrace.recorder.storage.CaptureOutput
import org.memotrace.recorder.storage.MediaDestination
import org.memotrace.recorder.storage.MediaEntry
import org.memotrace.recorder.storage.MediaIdentity
import org.memotrace.recorder.storage.UnlinkStatus
import org.memotrace.recorder.storage.UnlinkUnprovenException
import org.memotrace.recorder.storage.UnlinkWitness
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.io.FileNotFoundException
import java.io.IOException
import java.io.InputStream
import java.io.OutputStream

/** Contract fake, not proof of Android MediaProvider or filesystem durability. */
class FakeMediaDestination : MediaDestination {
    override val prefix = "Pictures/MemoTrace-test/"
    override val owner = "org.memotrace.recorder"

    class Item(
        val uri: String,
        var identity: MediaIdentity,
        var owner: String,
        var pending: Boolean = true,
    ) {
        var bytes = byteArrayOf()
        var trashed = false
        var linked = false
    }

    val items = linkedMapOf<String, Item>()
    var fault: String? = null
    var writesOpen = 0
    var readsOpen = 0
    var syncs = 0
    var witnessesOpen = 0
    var leaveLinkedOnDelete = false
    var unlinkStatus: UnlinkStatus? = null
    var unlinkFailure: Exception? = null
    var beforeInspect: (String) -> Unit = {}
    var afterPublish: (String) -> Unit = {}
    private var next = 0

    private fun fail(point: String) {
        if (fault == point) throw IOException(point)
    }

    override fun insert(identity: MediaIdentity): String {
        fail("insert")
        val uri = "content://media/external_primary/images/media/${++next}"
        items[uri] = Item(uri, identity, owner)
        fail("insert_after")
        return uri
    }

    private fun Item.entry() = MediaEntry(uri, identity.name, identity.path, owner, pending, bytes.size.toLong(), trashed)

    override fun find(identity: MediaIdentity): List<MediaEntry> {
        fail("find")
        return items.values
            .filter {
                it.identity.name == identity.name && it.identity.path == identity.path && it.owner == owner
            }.map { it.entry() }
    }

    override fun inspect(uri: String): MediaEntry? {
        beforeInspect(uri)
        fail("inspect")
        return items[uri]?.entry()
    }

    override fun openWrite(uri: String): CaptureOutput {
        fail("open_write")
        val item = checkNotNull(items[uri])
        item.linked = true
        writesOpen++
        return object : CaptureOutput {
            var closed = false
            val bytes = ByteArrayOutputStream()
            override val stream =
                object : OutputStream() {
                    override fun write(value: Int) {
                        check(!closed) { "closed_writer" }
                        fail("write")
                        bytes.write(value)
                        item.bytes = bytes.toByteArray()
                    }

                    override fun write(
                        buffer: ByteArray,
                        offset: Int,
                        length: Int,
                    ) {
                        check(!closed) { "closed_writer" }
                        fail("write")
                        bytes.write(buffer, offset, length)
                        item.bytes = bytes.toByteArray()
                    }
                }

            override fun sync() {
                check(!closed)
                fail("sync")
                syncs++
            }

            override fun close() {
                if (!closed) {
                    closed = true
                    writesOpen--
                    fail("close")
                }
            }
        }
    }

    override fun openRead(uri: String): InputStream {
        fail("open_read")
        val item = items[uri]?.takeIf { it.linked } ?: throw FileNotFoundException("not_materialized")
        readsOpen++
        return object : ByteArrayInputStream(item.bytes) {
            override fun read(
                buffer: ByteArray,
                off: Int,
                len: Int,
            ): Int {
                fail("read")
                return super.read(buffer, off, len)
            }

            override fun close() {
                readsOpen--
                super.close()
            }
        }
    }

    override fun publish(
        uri: String,
        identity: MediaIdentity,
    ) {
        fail("publish")
        val item = checkNotNull(items[uri])
        check(item.pending && item.owner == owner && item.identity.name == identity.name && item.identity.path == identity.path)
        item.pending = false
        fail("publish_after")
        afterPublish(uri)
    }

    override fun watchUnlink(uri: String): UnlinkWitness {
        val item = checkNotNull(items[uri])
        if (!item.linked) throw UnlinkUnprovenException("unlink_descriptor_missing", FileNotFoundException("not_materialized"))
        witnessesOpen++
        return object : UnlinkWitness {
            override fun status(): UnlinkStatus {
                unlinkFailure?.let { throw it }
                return unlinkStatus ?: if (item.linked) UnlinkStatus.STILL_LINKED else UnlinkStatus.PROVEN_UNLINKED
            }

            override fun close() {
                witnessesOpen--
            }
        }
    }

    override fun deletePending(
        uri: String,
        identity: MediaIdentity,
    ) {
        fail("delete")
        val item = checkNotNull(items[uri])
        check(
            item.pending && !item.trashed && item.owner == owner && item.identity.name == identity.name &&
                item.identity.path == identity.path,
        )
        watchUnlink(uri).use {
            items.remove(uri)
            if (!leaveLinkedOnDelete) item.linked = false
            val status = it.status()
            if (status != UnlinkStatus.PROVEN_UNLINKED) throw UnlinkUnprovenException("media_unlink_$status", status = status)
        }
    }
}

fun syntheticJpeg(): ByteArray {
    val bitmap = Bitmap.createBitmap(16, 12, Bitmap.Config.ARGB_8888)
    return ByteArrayOutputStream().use {
        check(bitmap.compress(Bitmap.CompressFormat.JPEG, 90, it))
        bitmap.recycle()
        it.toByteArray()
    }
}
