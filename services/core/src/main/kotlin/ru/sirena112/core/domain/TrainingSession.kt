package ru.sirena112.core.domain

import ru.sirena112.core.classifier.CardCalculation
import ru.sirena112.core.classifier.OperatorCardInput
import java.time.Duration
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

/** Устаревшая ревизия черновика: клиент перезаписал более новые данные. */
class CardRevisionConflictException(
    val sessionId: UUID,
    val expectedRevision: Int,
    val actualRevision: Int
) : IllegalStateException(
    "Устаревшая ревизия карточки сессии $sessionId: ожидается $actualRevision, получено $expectedRevision"
)

/**
 * Карточка оператора по контракту 0.3: исходные данные оператора и вычисленный
 * Core результат. Вычисляемые поля клиенту принадлежать не могут.
 */
data class OperatorCard(
    val input: OperatorCardInput = OperatorCardInput(),
    val calculation: CardCalculation? = null
)

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

    /** Растёт на каждое сохранение черновика; основа для optimistic locking. */
    var cardRevision: Int = 0
        private set

    var startedAt: Instant? = null
        private set

    var endedAt: Instant? = null
        private set

    var updatedAt: Instant = createdAt
        private set

    var failureReason: String? = null
        private set

    /** Событие о превышении лимита времени отправляется не более одного раза. */
    var timeLimitEventEmitted: Boolean = false
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
        startedAt = startedAt ?: Instant.now()
        return transition(SessionState.ACTIVE)
    }

    fun complete(): TrainingSession {
        endedAt = endedAt ?: Instant.now()
        return transition(SessionState.COMPLETED)
    }

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

    fun checkRevision(expectedRevision: Int?) {
        if (expectedRevision != null && expectedRevision != cardRevision) {
            throw CardRevisionConflictException(id, expectedRevision, cardRevision)
        }
    }

    fun updateCard(card: OperatorCard): TrainingSession {
        if (state !in CARD_UPDATE_STATES) {
            throw IllegalStateException("Карточку нельзя изменять в состоянии $state")
        }
        checkNoBlankInput(card)
        operatorCard = card
        cardRevision += 1
        touch()
        return this
    }

    fun timeLimitExceeded(now: Instant = Instant.now()): Boolean =
        startedAt != null &&
            state in setOf(SessionState.READY, SessionState.ACTIVE, SessionState.COMPLETED) &&
            Duration.between(startedAt, now) > Duration.ofSeconds(scenario.timeLimitSeconds.toLong())

    fun markTimeLimitEventEmitted() {
        timeLimitEventEmitted = true
    }

    private fun checkNoBlankInput(card: OperatorCard) {
        if (card.input.isEmpty() && card.calculation == null) {
            throw IllegalArgumentException("Карточка должна содержать хотя бы одно заполненное поле")
        }
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
