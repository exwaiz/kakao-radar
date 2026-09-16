package dev.kakaoradar.collector

/** Values are literal: whitespace and repeated text are meaningful in this collector. */
data class ObservedMessage(val sender: String, val text: String, val sourceTime: Long?)
data class DiffResult(val added: List<ObservedMessage>, val next: List<ObservedMessage>, val ambiguous: Boolean)

object MessageDiff {
    fun compare(previous: List<ObservedMessage>, current: List<ObservedMessage>): DiffResult {
        if (current.isEmpty()) return DiffResult(emptyList(), previous, false)
        if (previous.isEmpty()) return DiffResult(current, current, current.any { it.sourceTime == null })
        // A shorter redraw of a previously seen window does not create new messages.
        val contained = current.size <= previous.size &&
            (0..previous.size - current.size).any { previous.subList(it, it + current.size) == current }
        if (contained) return DiffResult(emptyList(), previous, current.any { it.sourceTime == null })
        val overlap = (minOf(previous.size, current.size) downTo 1).firstOrNull {
            previous.takeLast(it) == current.take(it)
        } ?: 0
        // No guessing when the window has no overlap: preserve data and expose uncertainty.
        val uncertain = overlap == 0 || current.any { it.sourceTime == null }
        return DiffResult(current.drop(overlap), current, uncertain)
    }
}
