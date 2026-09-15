package ru.sirena112.core.domain

import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertThrows
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import java.time.Instant
import java.util.UUID

class TrainingSessionTest {

    @Test
    fun `voice session follows the contract lifecycle`() {
        val session = TrainingSession(UUID.randomUUID(), scenario(), SessionMode.VOICE)

        session.markReady().onCallRinging().onCallAnswered().complete().startScoring().completeScoring()

        assertEquals(SessionState.SCORED, session.state)
    }

    @Test
    fun `card session starts directly from ready and cannot ring`() {
        val session = TrainingSession(UUID.randomUUID(), scenario(), SessionMode.CARD)

        session.markReady().startCard()

        assertEquals(SessionState.ACTIVE, session.state)
        assertThrows(IllegalStateException::class.java) { session.onCallRinging() }
    }

    @Test
    fun `forbidden transition returns a domain error with current and target`() {
        val sessionId = UUID.randomUUID()
        val session = TrainingSession(sessionId, scenario(), SessionMode.VOICE)

        val error = assertThrows(InvalidSessionTransitionException::class.java) { session.complete() }

        assertEquals(sessionId, error.sessionId)
        assertEquals(SessionState.CREATED, error.current)
        assertEquals(SessionState.COMPLETED, error.target)
        assertTrue(error.message!!.contains("CREATED -> COMPLETED"))
    }

    @Test
    fun `failure is allowed during execution but terminal states cannot change`() {
        val failed = TrainingSession(UUID.randomUUID(), scenario(), SessionMode.VOICE)
            .markReady().onCallRinging().fail("media unavailable")
        assertEquals(SessionState.FAILED, failed.state)
        assertEquals("media unavailable", failed.failureReason)

        assertThrows(InvalidSessionTransitionException::class.java) { failed.markReady() }

        val scored = TrainingSession(UUID.randomUUID(), scenario(), SessionMode.CARD)
            .markReady().startCard().complete().startScoring().completeScoring()
        assertThrows(InvalidSessionTransitionException::class.java) { scored.fail("late error") }
    }

    @Test
    fun `card can be updated only before completion`() {
        val session = TrainingSession(UUID.randomUUID(), scenario(), SessionMode.CARD).markReady()
        val card = OperatorCard(incidentType = "Пожар", address = "Москва")

        session.updateCard(card).startCard()
        assertEquals(card, session.operatorCard)

        session.complete()
        assertThrows(IllegalStateException::class.java) { session.updateCard(OperatorCard()) }
    }

    @Test
    fun `event repository is idempotent by event id`() {
        val repository = InMemorySessionEventRepository()
        val sessionId = UUID.randomUUID()
        val eventId = UUID.randomUUID()
        val event = SessionEvent(
            eventId = eventId,
            sessionId = sessionId,
            type = SessionEventType.TRANSCRIPT_FINAL.value,
            timestamp = Instant.parse("2026-09-15T12:00:05.420Z"),
            source = EventSource.MEDIA.value,
            payload = mapOf("text" to "пожар")
        )

        assertTrue(repository.saveIfAbsent(event))
        assertFalse(repository.saveIfAbsent(event.copy(payload = mapOf("text" to "дубликат"))))
        assertEquals(event, repository.findById(eventId))
        assertEquals(1, repository.findBySessionId(sessionId).size)
    }

    private fun scenario(): Scenario = Scenario.draft(
        title = "Пожар в здании",
        category = Category.FIRE,
        difficulty = Difficulty.BASIC,
        profile = "operator",
        groundTruth = GroundTruth(
            incidentType = "пожар",
            ekpCode = "1010101",
            signs = IncidentSigns("здание"),
            requiredServices = setOf("Служба 101")
        ),
        rubric = Rubric(listOf(RubricCriterion("ADDRESS", "Адрес", 1.0)))
    )
}
