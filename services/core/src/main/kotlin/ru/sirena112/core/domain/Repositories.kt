package ru.sirena112.core.domain

import java.util.UUID
import java.util.concurrent.ConcurrentHashMap

interface ScenarioRepository {
    fun save(scenario: Scenario): Scenario
    fun findById(id: UUID): Scenario?
    fun findAll(): List<Scenario>
}

class InMemoryScenarioRepository : ScenarioRepository {
    private val scenarios = ConcurrentHashMap<UUID, Scenario>()

    override fun save(scenario: Scenario): Scenario {
        scenarios[scenario.id] = scenario
        return scenario
    }

    override fun findById(id: UUID): Scenario? = scenarios[id]

    override fun findAll(): List<Scenario> = scenarios.values.sortedBy { it.id.toString() }
}

interface TrainingSessionRepository {
    fun save(session: TrainingSession): TrainingSession
    fun findById(id: UUID): TrainingSession?
    fun findAll(): List<TrainingSession>
}

class InMemoryTrainingSessionRepository : TrainingSessionRepository {
    private val sessions = ConcurrentHashMap<UUID, TrainingSession>()

    override fun save(session: TrainingSession): TrainingSession {
        sessions[session.id] = session
        return session
    }

    override fun findById(id: UUID): TrainingSession? = sessions[id]

    override fun findAll(): List<TrainingSession> = sessions.values.sortedBy { it.createdAt }
}

interface SessionEventRepository {
    /** Возвращает false, если eventId уже был сохранён (идемпотентность). */
    fun saveIfAbsent(event: SessionEvent): Boolean
    fun findById(eventId: UUID): SessionEvent?
    fun findBySessionId(sessionId: UUID): List<SessionEvent>
}

class InMemorySessionEventRepository : SessionEventRepository {
    private val events = ConcurrentHashMap<UUID, SessionEvent>()

    override fun saveIfAbsent(event: SessionEvent): Boolean = events.putIfAbsent(event.eventId, event) == null

    override fun findById(eventId: UUID): SessionEvent? = events[eventId]

    override fun findBySessionId(sessionId: UUID): List<SessionEvent> = events.values
        .asSequence()
        .filter { it.sessionId == sessionId }
        .sortedBy { it.timestamp }
        .toList()
}
