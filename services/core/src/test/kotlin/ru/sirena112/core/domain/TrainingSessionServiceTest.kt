package ru.sirena112.core.domain

import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertThrows
import org.junit.jupiter.api.Test
import java.util.UUID

class TrainingSessionServiceTest {

    @Test
    fun `service persists aggregate transitions and contract events`() {
        val sessions = InMemoryTrainingSessionRepository()
        val events = InMemorySessionEventRepository()
        val service = TrainingSessionService(sessions, events)
        val sessionId = UUID.randomUUID()

        service.create(scenario(), SessionMode.CARD, sessionId)
        service.markReady(sessionId)
        service.startCard(sessionId)
        service.complete(sessionId)
        service.startScoring(sessionId)
        service.completeScoring(sessionId)

        assertEquals(SessionState.SCORED, sessions.findById(sessionId)!!.state)
        assertEquals(
            listOf("session.created", "session.started", "session.completed", "score.started", "score.completed"),
            events.findBySessionId(sessionId).map { it.type }
        )
    }

    @Test
    fun `service rejects unknown sessions`() {
        val service = TrainingSessionService(InMemoryTrainingSessionRepository(), InMemorySessionEventRepository())

        assertThrows(NoSuchElementException::class.java) { service.markReady(UUID.randomUUID()) }
    }

    private fun scenario(): Scenario = Scenario.draft(
        title = "Пожар в здании",
        category = Category.FIRE,
        difficulty = Difficulty.BASIC,
        profile = "operator",
        groundTruth = GroundTruth("пожар", requiredServices = setOf("Служба 101")),
        rubric = Rubric(listOf(RubricCriterion("ADDRESS", "Адрес", 1.0)))
    )
}
