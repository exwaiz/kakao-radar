package dev.kakaoradar.collector

import org.junit.Assert.*
import org.junit.Test

class MessageDiffTest {
    private fun m(text: String, time: Long? = 100) = ObservedMessage("sender", text, time)
    @Test fun firstWindowPreservesEveryOccurrence() {
        val messages = listOf(m("네"), m("네"))
        assertEquals(messages, MessageDiff.compare(emptyList(), messages).added)
    }
    @Test fun identicalRedrawAddsNothing() {
        val messages = listOf(m("a"), m("b", 101))
        assertTrue(MessageDiff.compare(messages, messages).added.isEmpty())
    }
    @Test fun cumulativeUpdateOnlyAddsTail() {
        assertEquals(listOf(m("c", 102)), MessageDiff.compare(listOf(m("a"), m("b", 101)), listOf(m("a"), m("b", 101), m("c", 102))).added)
    }
    @Test fun rollingWindowOnlyAddsTail() {
        assertEquals(listOf(m("c", 102)), MessageDiff.compare(listOf(m("a"), m("b", 101)), listOf(m("b", 101), m("c", 102))).added)
    }
    @Test fun sameTextAtDifferentTimesIsNotCollapsed() {
        assertEquals(listOf(m("네", 101)), MessageDiff.compare(listOf(m("네")), listOf(m("네"), m("네", 101))).added)
    }
    @Test fun duplicateMultiplicityWithinWindowIsPreserved() {
        assertEquals(listOf(m("네")), MessageDiff.compare(listOf(m("네")), listOf(m("네"), m("네"))).added)
    }
    @Test fun shrinkingWindowDoesNotErasePreviousContext() {
        val old = listOf(m("a"), m("b", 101))
        val result = MessageDiff.compare(old, listOf(m("a")))
        assertTrue(result.added.isEmpty()); assertEquals(old, result.next)
    }
    @Test fun noOverlapPreservesDataButMarksUncertainty() {
        val result = MessageDiff.compare(listOf(m("a")), listOf(m("b", 200)))
        assertEquals(listOf(m("b", 200)), result.added); assertTrue(result.ambiguous)
    }
    @Test fun missingTimeIsExplicitlyUncertainEvenWhenSuppressed() {
        val old = listOf(m("네", null))
        assertTrue(MessageDiff.compare(old, old).ambiguous)
    }
    @Test fun emptyRedrawDoesNotResetSnapshot() {
        val old = listOf(m("a"))
        assertEquals(old, MessageDiff.compare(old, emptyList()).next)
    }
    @Test fun whitespaceIsNotNormalizedAway() {
        assertEquals(listOf(m(" a")), MessageDiff.compare(listOf(m("a")), listOf(m(" a"))).added)
    }
}
