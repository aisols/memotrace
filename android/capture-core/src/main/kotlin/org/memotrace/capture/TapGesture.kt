package org.memotrace.capture

/** One DOWN-anchored target; displacement, not accumulated tremor distance. */
class TapGesture(
    private val slip: Float,
) {
    init {
        require(slip.isFinite() && slip > 0)
    }

    var active = false
        private set
    private var downX = 0f
    private var downY = 0f

    fun down(
        x: Float,
        y: Float,
    ) {
        downX = x
        downY = y
        active = true
    }

    fun move(
        x: Float,
        y: Float,
    ) {
        val dx = x - downX
        val dy = y - downY
        if (dx * dx + dy * dy > slip * slip) cancel()
    }

    fun up(
        x: Float,
        y: Float,
    ): Boolean {
        move(x, y)
        val click = active
        cancel()
        return click
    }

    fun cancel() {
        active = false
    }
}
