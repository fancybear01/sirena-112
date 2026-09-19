package ru.sirena112.core.dispatch

import org.junit.jupiter.api.Assertions.*
import org.junit.jupiter.api.Test
import ru.sirena112.core.classifier.*
import ru.sirena112.core.domain.*
import java.time.Clock
import java.time.Instant
import java.time.ZoneId
import java.time.ZoneOffset
import java.util.UUID

class ServiceAssignmentTest {
    private val sessions = InMemoryTrainingSessionRepository()
    private val events = InMemorySessionEventRepository()
    private val clock = MutableClock()
    private val service = ServiceAssignmentService(sessions, events, clock, 60)

    private fun session(status: CalculationStatus = CalculationStatus.RESOLVED,
        services: List<RoutedService> = listOf("MCHS", "POLICE").map { RoutedService(it, it, emptyList()) }
    ): TrainingSession {
        val scenario = Scenario.draft("Учебный сценарий", Category.FIRE, Difficulty.BASIC, "operator",
            GroundTruth(classifierVersion = "test", classifierCode = "1010101", incidentType = "пожар",
                ekp35IncidentType = null, responseScenarioCode = null,
                responseScenarioStatus = ResponseScenarioStatus.MISSING, mainServices = emptyList(),
                requiredServices = emptyList(), expectedInput = OperatorCardInput()),
            Rubric(listOf(RubricCriterion("ADDRESS", "Адрес", 1.0))))
        return sessions.save(TrainingSession(UUID.randomUUID(), scenario, SessionMode.CARD,
            state = SessionState.ACTIVE, operatorCard = OperatorCard(calculation =
                CardCalculation(status, "test", services = services))))
    }

    private fun change(assignment: ServiceAssignment, status: ServiceStatus, reason: String? = null) =
        service.changeStatus(assignment.sessionId, assignment.id,
            ChangeServiceStatusRequest(UUID.randomUUID(), status, "Учебное изменение", reason))

    @Test
    fun `services are independent history survives reads and session stays active`() {
        val session = session()
        val initial = service.assignSubmittedCard(session.id)
        assertEquals(initial, service.assignSubmittedCard(session.id))
        val first = initial.first()
        listOf(ServiceStatus.RECEIVED, ServiceStatus.ACCEPTED, ServiceStatus.RESPONDING,
            ServiceStatus.ARRIVED, ServiceStatus.COMPLETED).forEach {
            clock.now = clock.now.plusSeconds(1)
            change(first, it)
        }
        val result = service.list(session.id)
        assertEquals(ServiceStatus.COMPLETED, result[0].status)
        assertEquals(ServiceStatus.ADDED, result[1].status)
        assertEquals(SessionState.ACTIVE, session.state)
        assertEquals((1..6).toList(), result[0].history.map { it.sequence })
        assertEquals(result, service.list(session.id))
        assertTrue(result[0].history.zipWithNext().all { (a, b) -> a.timestamp <= b.timestamp })
        assertEquals(7, events.findBySessionId(session.id).size)
        assertEquals(result[0].history.last().eventId, events.findBySessionId(session.id).last().eventId)
    }

    @Test
    fun `illegal transition duplicate and event id collision leave all state unchanged`() {
        val assignment = service.assignSubmittedCard(session().id).first()
        assertThrows(IllegalStateException::class.java) { change(assignment, ServiceStatus.ARRIVED) }
        assertEquals(assignment, service.list(assignment.sessionId).first())
        val command = ChangeServiceStatusRequest(UUID.randomUUID(), ServiceStatus.RECEIVED)
        val updated = service.changeStatus(assignment.sessionId, assignment.id, command)
        assertThrows(IllegalStateException::class.java) {
            service.changeStatus(assignment.sessionId, assignment.id, command)
        }
        assertEquals(updated, service.list(assignment.sessionId).first())
        val other = service.list(assignment.sessionId)[1]
        assertThrows(IllegalStateException::class.java) {
            service.changeStatus(other.sessionId, other.id, command)
        }
        assertEquals(other, service.list(other.sessionId)[1])
        assertEquals(3, events.findBySessionId(assignment.sessionId).size)
    }

    @Test
    fun `refusal requires reason and terminal states reject further transitions`() {
        val assignment = service.assignSubmittedCard(session().id).first()
        change(assignment, ServiceStatus.RECEIVED)
        assertThrows(IllegalArgumentException::class.java) { change(assignment, ServiceStatus.REFUSED) }
        val refused = change(assignment, ServiceStatus.REFUSED, "Не наша территория")
        assertEquals("Не наша территория", refused.history.last().refusalReason)
        assertThrows(IllegalStateException::class.java) { change(assignment, ServiceStatus.ACCEPTED) }
        val another = service.list(assignment.sessionId)[1]
        change(another, ServiceStatus.FAILED)
        assertThrows(IllegalStateException::class.java) { change(another, ServiceStatus.RECEIVED) }
    }

    @Test
    fun `deadline is configurable derived at read and does not mutate status or history`() {
        val assignment = service.assignSubmittedCard(session().id).first()
        assertFalse(service.list(assignment.sessionId).first().overdue)
        clock.now = clock.now.plusSeconds(60)
        val overdue = service.list(assignment.sessionId).first()
        assertTrue(overdue.overdue)
        assertEquals(assignment.history, overdue.history)
        assertEquals(ServiceStatus.ADDED, overdue.status)
        assertFalse(change(assignment, ServiceStatus.FAILED).overdue)
        assertThrows(IllegalArgumentException::class.java) { ServiceAssignmentService(sessions, events, clock, 0) }
    }

    @Test
    fun `unresolved route rejected empty route allowed and cross session access denied`() {
        val incomplete = session(CalculationStatus.INCOMPLETE)
        assertThrows(IllegalStateException::class.java) { service.assignSubmittedCard(incomplete.id) }
        assertTrue(service.list(incomplete.id).isEmpty())
        assertTrue(service.assignSubmittedCard(session(services = emptyList()).id).isEmpty())
        val assignment = service.assignSubmittedCard(session().id).first()
        assertThrows(NoSuchElementException::class.java) {
            service.changeStatus(incomplete.id, assignment.id,
                ChangeServiceStatusRequest(UUID.randomUUID(), ServiceStatus.RECEIVED))
        }
        assertThrows(NoSuchElementException::class.java) { service.list(UUID.randomUUID()) }
    }

    @Test
    fun `clock rollback cannot reorder history timestamps`() {
        val assignment = service.assignSubmittedCard(session().id).first()
        clock.now = clock.now.minusSeconds(30)
        val updated = change(assignment, ServiceStatus.RECEIVED)
        assertEquals(assignment.createdAt, updated.updatedAt)
        assertEquals(listOf(1, 2), updated.history.map { it.sequence })
    }

    @Test
    fun `concurrent duplicate only appends once`() {
        val assignment = service.assignSubmittedCard(session().id).first()
        val command = ChangeServiceStatusRequest(UUID.randomUUID(), ServiceStatus.RECEIVED)
        val executor = java.util.concurrent.Executors.newFixedThreadPool(2)
        try {
            val futures = (1..2).map {
                executor.submit(java.util.concurrent.Callable {
                    runCatching { service.changeStatus(assignment.sessionId, assignment.id, command) }
                })
            }
            val results = futures.map { it.get(5, java.util.concurrent.TimeUnit.SECONDS) }
            assertEquals(1, results.count { it.isSuccess })
            assertTrue(results.single { it.isFailure }.exceptionOrNull() is IllegalStateException)
            assertEquals(2, service.list(assignment.sessionId).first().history.size)
            assertEquals(1, events.findBySessionId(assignment.sessionId).count { it.eventId == command.eventId })
        } finally { executor.shutdownNow() }
    }

    @Test
    fun `all transitions conform to explicit matrix`() {
        val normal = listOf(ServiceStatus.ADDED, ServiceStatus.RECEIVED, ServiceStatus.ACCEPTED,
            ServiceStatus.RESPONDING, ServiceStatus.ARRIVED, ServiceStatus.COMPLETED).zipWithNext().toSet()
        for (from in ServiceStatus.values()) for (to in ServiceStatus.values()) {
            val expected = (from to to) in normal || (!from.terminal && to == ServiceStatus.FAILED) ||
                (from in setOf(ServiceStatus.RECEIVED, ServiceStatus.ACCEPTED) && to == ServiceStatus.REFUSED)
            assertEquals(expected, from.canTransitionTo(to), "$from -> $to")
        }
    }

    private class MutableClock(var now: Instant = Instant.parse("2026-09-19T00:00:00Z")) : Clock() {
        override fun instant(): Instant = now
        override fun getZone(): ZoneId = ZoneOffset.UTC
        override fun withZone(zone: ZoneId): Clock = this
    }
}
