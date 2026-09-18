package ru.sirena112.core.domain

import java.time.Instant
import java.util.UUID

enum class SessionEventType(val value: String) {
    SESSION_CREATED("session.created"),
    SESSION_STARTED("session.started"),
    SESSION_COMPLETED("session.completed"),
    CALL_RINGING("call.ringing"),
    CALL_ANSWERED("call.answered"),
    CALL_ENDED("call.ended"),
    TRANSCRIPT_PARTIAL("transcript.partial"),
    TRANSCRIPT_FINAL("transcript.final"),
    OPERATOR_SPEECH_STARTED("operator.speech_started"),
    OPERATOR_SPEECH_ENDED("operator.speech_ended"),
    CALLER_INTERRUPTED("caller.interrupted"),
    OPERATOR_CARD_UPDATED("operator.card_updated"),
    CARD_ANSWERS_UPDATED("card.answers_updated"),
    ROUTING_CALCULATED("routing.calculated"),
    CARD_TIME_LIMIT_EXCEEDED("card.time_limit_exceeded"),
    OPERATOR_ANSWER_SUBMITTED("operator.answer_submitted"),
    SCORE_STARTED("score.started"),
    SCORE_COMPLETED("score.completed"),
    SYSTEM_ERROR("system.error")
}

enum class EventSource(val value: String) {
    CORE("core"),
    MEDIA("media"),
    AI("ai"),
    ANY("any")
}

/** Неизменяемый конверт события из contracts/events.md. */
data class SessionEvent(
    val eventId: UUID,
    val sessionId: UUID,
    val type: String,
    val timestamp: Instant,
    val source: String,
    val payload: Map<String, Any?> = emptyMap()
) {
    init {
        require(type.isNotBlank()) { "Тип события не может быть пустым" }
        require(source.isNotBlank()) { "Источник события не может быть пустым" }
    }

    companion object {
        fun create(
            sessionId: UUID,
            type: SessionEventType,
            source: EventSource,
            payload: Map<String, Any?> = emptyMap(),
            eventId: UUID = UUID.randomUUID(),
            timestamp: Instant = Instant.now()
        ): SessionEvent = SessionEvent(
            eventId = eventId,
            sessionId = sessionId,
            type = type.value,
            timestamp = timestamp,
            source = source.value,
            payload = payload.toMap()
        )
    }
}
