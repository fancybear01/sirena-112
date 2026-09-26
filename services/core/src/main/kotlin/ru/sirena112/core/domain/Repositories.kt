package ru.sirena112.core.domain

import java.util.UUID
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.CopyOnWriteArrayList

interface ScenarioRepository {
    fun save(scenario: Scenario): Scenario
    /** Inserts a validated package without replacing an existing scenario. */
    fun insertAllNew(scenarios: List<Scenario>)
    fun findById(id: UUID): Scenario?
    fun findAll(): List<Scenario>
}

class InMemoryScenarioRepository : ScenarioRepository {
    private val scenarios = ConcurrentHashMap<UUID, Scenario>()

    override fun save(scenario: Scenario): Scenario {
        scenarios[scenario.id] = scenario
        return scenario
    }

    @Synchronized
    override fun insertAllNew(scenarios: List<Scenario>) {
        require(scenarios.map { it.id }.distinct().size == scenarios.size) { "Повторяющиеся id в пакете" }
        if (scenarios.any { this.scenarios.containsKey(it.id) }) {
            throw IllegalStateException("Сценарий с таким id уже существует")
        }
        scenarios.forEach { this.scenarios[it.id] = it }
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

/** Локальная подписка на новые события; заменяется брокером при масштабировании. */
interface SessionEventSubscription {
    fun subscribe(sessionId: UUID, listener: (SessionEvent) -> Unit): () -> Unit
}

class InMemorySessionEventRepository : SessionEventRepository, SessionEventSubscription {
    /** Linked map keeps append order when several events share the same Instant. */
    private val events = LinkedHashMap<UUID, SessionEvent>()
    private val listeners = ConcurrentHashMap<UUID, CopyOnWriteArrayList<(SessionEvent) -> Unit>>()

    @Synchronized
    override fun saveIfAbsent(event: SessionEvent): Boolean {
        if (events.containsKey(event.eventId)) return false
        events[event.eventId] = event
        listeners[event.sessionId]?.forEach { listener ->
            runCatching { listener(event) }
        }
        return true
    }

    @Synchronized
    override fun findById(eventId: UUID): SessionEvent? = events[eventId]

    @Synchronized
    override fun findBySessionId(sessionId: UUID): List<SessionEvent> = events.values
        .asSequence()
        .filter { it.sessionId == sessionId }
        .toList()

    override fun subscribe(sessionId: UUID, listener: (SessionEvent) -> Unit): () -> Unit {
        val sessionListeners = listeners.computeIfAbsent(sessionId) { CopyOnWriteArrayList() }
        sessionListeners += listener
        return {
            sessionListeners.remove(listener)
            if (sessionListeners.isEmpty()) listeners.remove(sessionId, sessionListeners)
        }
    }

}
