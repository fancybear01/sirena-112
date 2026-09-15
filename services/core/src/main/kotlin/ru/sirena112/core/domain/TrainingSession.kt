package ru.sirena112.core.domain

import java.time.Instant
import java.util.UUID

enum class SessionMode {
    VOICE,
    CARD
}

enum class SessionState {
    CREATED,
    READY,
    RINGING,
    ACTIVE,
    COMPLETED,
    SCORING,
    SCORED,
    FAILED
}

typealias TrainingSessionState = SessionState

class InvalidSessionTransitionException(
    val sessionId: UUID,
    val current: SessionState,
    val target: SessionState,
    message: String = "Недопустимый переход учебной сессии $sessionId: $current -> $target"
) : IllegalStateException(message)

/** Карточный ответ оператора. Поля названы так же, как в сценарном контракте. */
data class OperatorCard(
    val incidentType: String? = null,
    val signs: IncidentSigns? = null,
    val address: String? = null,
    val requiredServices: Set<String> = emptySet(),
    val facts: Map<String, Any?> = emptyMap()
) {
    init {
        require(requiredServices.all { it.isNotBlank() }) { "Службы в карточке не могут быть пустыми" }
    }
}

/**
 * Агрегат учебной сессии. Статус меняется только через доменные методы,
 * поэтому переходы остаются едиными для карточного и голосового режимов.
 */
class TrainingSession(
    val id: UUID,
    val scenario: Scenario,
    val mode: SessionMode,
    state: SessionState = SessionState.CREATED,
    operatorCard: OperatorCard = OperatorCard(),
    val createdAt: Instant = Instant.now()
) {
    var state: SessionState = state
        private set

    var operatorCard: OperatorCard = operatorCard
        private set

    var updatedAt: Instant = createdAt
        private set

    var failureReason: String? = null
        private set

    fun markReady(): TrainingSession = transition(SessionState.READY)

    fun onCallRinging(): TrainingSession {
        requireMode(SessionMode.VOICE, "Звонок доступен только в голосовом режиме")
        return transition(SessionState.RINGING)
    }

    fun onCallAnswered(): TrainingSession {
        requireMode(SessionMode.VOICE, "Ответ на звонок доступен только в голосовом режиме")
        return transition(SessionState.ACTIVE)
    }

    fun startCard(): TrainingSession {
        requireMode(SessionMode.CARD, "Карточный старт доступен только в карточном режиме")
        return transition(SessionState.ACTIVE)
    }

    fun complete(): TrainingSession = transition(SessionState.COMPLETED)

    fun startScoring(): TrainingSession = transition(SessionState.SCORING)

    fun completeScoring(): TrainingSession = transition(SessionState.SCORED)

    fun fail(reason: String? = null): TrainingSession {
        if (state !in FAILURE_SOURCES) {
            throw InvalidSessionTransitionException(id, state, SessionState.FAILED)
        }
        state = SessionState.FAILED
        failureReason = reason?.takeIf { it.isNotBlank() }
        touch()
        return this
    }

    fun updateCard(card: OperatorCard): TrainingSession {
        if (state !in CARD_UPDATE_STATES) {
            throw IllegalStateException("Карточку нельзя изменять в состоянии $state")
        }
        operatorCard = card
        touch()
        return this
    }

    private fun transition(target: SessionState): TrainingSession {
        if (state !in ALLOWED_TRANSITIONS || target !in ALLOWED_TRANSITIONS.getValue(state)) {
            throw InvalidSessionTransitionException(id, state, target)
        }
        state = target
        touch()
        return this
    }

    private fun requireMode(expected: SessionMode, message: String) {
        if (mode != expected) {
            throw IllegalStateException(message)
        }
    }

    private fun touch() {
        updatedAt = Instant.now()
    }

    companion object {
        private val ALLOWED_TRANSITIONS = mapOf(
            SessionState.CREATED to setOf(SessionState.READY),
            SessionState.READY to setOf(SessionState.RINGING, SessionState.ACTIVE),
            SessionState.RINGING to setOf(SessionState.ACTIVE),
            SessionState.ACTIVE to setOf(SessionState.COMPLETED),
            SessionState.COMPLETED to setOf(SessionState.SCORING),
            SessionState.SCORING to setOf(SessionState.SCORED)
        )

        private val FAILURE_SOURCES = setOf(
            SessionState.RINGING,
            SessionState.ACTIVE,
            SessionState.COMPLETED,
            SessionState.SCORING
        )

        private val CARD_UPDATE_STATES = setOf(SessionState.READY, SessionState.ACTIVE)
    }
}
