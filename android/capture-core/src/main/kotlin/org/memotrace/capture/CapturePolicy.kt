package org.memotrace.capture

import kotlin.math.abs

class CaptureConfig(
    val baselineMs: Long = 2_000,
    val motionMs: Long = 1_000,
    val analysisMs: Long = 250,
    val motionEnter: Double = 12.0,
    val motionExit: Double = 5.0,
    val quietMs: Long = 3_000,
    val captureTimeoutMs: Long = 30_000,
) {
    init {
        require(baselineMs in 1_000..10_000)
        require(motionMs in 500..baselineMs)
        require(analysisMs in 100..1_000)
        require(motionEnter.isFinite() && motionEnter in 1.0..255.0)
        require(motionExit.isFinite() && motionExit >= 0 && motionExit < motionEnter)
        require(quietMs in 500..30_000)
        require(captureTimeoutMs in 5_000..120_000)
    }
}

/** Monotonic milliseconds only. A single owner serializes all calls. */
class CapturePolicy(
    val config: CaptureConfig = CaptureConfig(),
) {
    enum class State { PAUSED, RECORDING, ERROR }

    var state = State.PAUSED
        private set
    var moving = false
        private set
    val intervalMs: Long get() = if (moving) config.motionMs else config.baselineMs
    private var quietSince: Long? = null
    private var lastRequest: Long? = null
    private var sequence = 0L
    private var pending: Long? = null

    fun start(): Boolean {
        if (state == State.RECORDING || pending != null) return false
        state = State.RECORDING
        lastRequest = null
        quietSince = null
        moving = false
        return true
    }

    fun pause() {
        state = State.PAUSED
    }

    fun fail() {
        state = State.ERROR
    }

    fun motion(
        score: Double,
        now: Long,
    ) {
        require(score.isFinite() && score in 0.0..255.0)
        if (score >= config.motionEnter) {
            moving = true
            quietSince = null
        } else if (score <= config.motionExit) {
            val since = quietSince ?: now.also { quietSince = it }
            if (now - since >= config.quietMs) moving = false
        } else {
            quietSince = null
        }
    }

    /** No queued ticks or catch-up bursts. Busy includes durable persistence. */
    fun request(now: Long): Long? {
        if (state != State.RECORDING || pending != null) return null
        val last = lastRequest
        if (last != null && now - last < intervalMs) return null
        lastRequest = now
        return (++sequence).also { pending = it }
    }

    fun timedOut(now: Long): Boolean = pending != null && now - checkNotNull(lastRequest) >= config.captureTimeoutMs

    /** A late completion frees its slot, but cannot undo pause/error. */
    fun complete(
        token: Long,
        success: Boolean,
    ): Boolean {
        if (token != pending) return false
        pending = null
        if (!success && state == State.RECORDING) fail()
        return state == State.RECORDING
    }
}

class LumaMetrics(
    val mean: Double,
    val variance: Double,
    val motion: Double,
    val coverSuspected: Boolean,
)

/** Fixed-size, transient luma samples. Darkness is never an acquisition input. */
class LumaAnalyzer(
    private val config: CaptureConfig = CaptureConfig(),
) {
    private var previous: IntArray? = null
    private var lastAnalysis: Long? = null
    private var covered = false

    fun due(now: Long): Boolean {
        val last = lastAnalysis
        if (last != null && now - last < config.analysisMs) return false
        lastAnalysis = now
        return true
    }

    fun analyze(samples: IntArray): LumaMetrics {
        require(samples.isNotEmpty() && samples.size <= 768)
        require(samples.all { it in 0..255 })
        val mean = samples.average()
        val variance = samples.sumOf { (it - mean) * (it - mean) } / samples.size
        val old = previous
        val motion =
            if (old == null || old.size != samples.size) {
                0.0
            } else {
                samples.indices.sumOf { abs(samples[it] - old[it]).toDouble() } / samples.size
            }
        previous = samples.copyOf()
        covered = if (covered) mean < 24.0 && variance < 64.0 else mean <= 12.0 && variance <= 25.0
        return LumaMetrics(mean, variance, motion, covered)
    }
}
