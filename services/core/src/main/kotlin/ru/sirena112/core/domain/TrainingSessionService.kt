package ru.sirena112.core.domain

import java.util.UUID

/** Оркестратор агрегата; конкретное хранилище подменяется интерфейсом репозитория. */
class TrainingSessionService(
    private val sessions: TrainingSessionRepository,
    private val events: SessionEventRepository
) {
    fun create(scenario: Scenario, mode: SessionMode, sessionId: UUID = UUID.randomUUID()): TrainingSession {
        val session = TrainingSession(sessionId, scenario, mode)
        sessions.save(session)
        append(session, SessionEventType.SESSION_CREATED, EventSource.CORE, mapOf("mode" to mode.name))
        return session
    }

    fun markReady(sessionId: UUID): TrainingSession = transition(sessionId) {
        it.markReady()
    }

    fun ring(sessionId: UUID): TrainingSession = transition(sessionId) {
        it.onCallRinging()
    }.also { append(it, SessionEventType.CALL_RINGING, EventSource.MEDIA) }

    fun answer(sessionId: UUID): TrainingSession = transition(sessionId) {
        it.onCallAnswered()
    }.also {
        append(it, SessionEventType.CALL_ANSWERED, EventSource.MEDIA)
        append(it, SessionEventType.SESSION_STARTED, EventSource.CORE)
    }

    fun startCard(sessionId: UUID): TrainingSession = transition(sessionId) {
        it.startCard()
    }.also { append(it, SessionEventType.SESSION_STARTED, EventSource.CORE) }

    fun complete(sessionId: UUID): TrainingSession = transition(sessionId) {
        it.complete()
    }.also { append(it, SessionEventType.SESSION_COMPLETED, EventSource.CORE) }

    fun startScoring(sessionId: UUID): TrainingSession = transition(sessionId) {
        it.startScoring()
    }.also { append(it, SessionEventType.SCORE_STARTED, EventSource.CORE) }

    fun completeScoring(sessionId: UUID): TrainingSession = transition(sessionId) {
        it.completeScoring()
    }.also { append(it, SessionEventType.SCORE_COMPLETED, EventSource.CORE) }

    fun fail(sessionId: UUID, reason: String? = null): TrainingSession = transition(sessionId) {
        it.fail(reason)
    }.also {
        append(it, SessionEventType.SYSTEM_ERROR, EventSource.CORE, reason?.let { value -> mapOf("reason" to value) }
            ?: emptyMap())
    }

    /**
     * Сохранение черновика с событиями классификации. События публикуются только
     * после успешного обновления агрегата и инкремента ревизии.
     */
    fun updateCard(
        sessionId: UUID,
        card: OperatorCard,
        events: List<Pair<SessionEventType, Map<String, Any?>>> = emptyList()
    ): TrainingSession {
        val session = requireSession(sessionId).updateCard(card)
        sessions.save(session)
        events.forEach { (type, payload) -> append(session, type, EventSource.CORE, payload) }
        append(session, SessionEventType.OPERATOR_CARD_UPDATED, EventSource.CORE)
        return session
    }

    /** Публикация единичного события от Core; используется для card.time_limit_exceeded. */
    fun appendEvent(sessionId: UUID, type: SessionEventType, payload: Map<String, Any?> = emptyMap()) {
        append(requireSession(sessionId), type, EventSource.CORE, payload)
    }

    /** Фиксирует отправку ответа, не меняя состояние агрегата. */
    fun submitAnswer(sessionId: UUID): TrainingSession {
        val session = requireSession(sessionId)
        if (session.state !in setOf(SessionState.ACTIVE, SessionState.COMPLETED)) {
            throw IllegalStateException("Ответ нельзя отправить в состоянии ${session.state}")
        }
        append(session, SessionEventType.OPERATOR_ANSWER_SUBMITTED, EventSource.CORE)
        return session
    }

    private fun transition(sessionId: UUID, action: (TrainingSession) -> TrainingSession): TrainingSession {
        val session = action(requireSession(sessionId))
        sessions.save(session)
        return session
    }

    private fun requireSession(sessionId: UUID): TrainingSession = sessions.findById(sessionId)
        ?: throw NoSuchElementException("Учебная сессия $sessionId не найдена")

    private fun append(
        session: TrainingSession,
        type: SessionEventType,
        source: EventSource,
        payload: Map<String, Any?> = emptyMap()
    ) {
        events.saveIfAbsent(SessionEvent.create(session.id, type, source, payload))
    }
}
