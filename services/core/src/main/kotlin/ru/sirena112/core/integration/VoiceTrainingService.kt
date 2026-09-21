package ru.sirena112.core.integration

import org.springframework.stereotype.Component
import org.springframework.stereotype.Service
import ru.sirena112.core.domain.EventSource
import ru.sirena112.core.domain.SessionEvent
import ru.sirena112.core.domain.SessionEventRepository
import ru.sirena112.core.domain.SessionEventType
import ru.sirena112.core.domain.SessionMode
import ru.sirena112.core.domain.SessionState
import ru.sirena112.core.domain.TrainingSessionRepository
import ru.sirena112.core.domain.TrainingSessionService
import java.util.UUID
import java.util.concurrent.ConcurrentHashMap

data class VoiceCallView(
    val callId: String,
    val sessionId: UUID,
    val aiSessionId: String,
    val sipAddress: String,
    val state: String
)

private data class VoiceCallContext(
    val sessionId: UUID,
    val aiSessionId: String,
    val sipAddress: String,
    var callId: String? = null,
    var state: String = "STARTING",
    var aiClosed: Boolean = false
) {
    fun toView(): VoiceCallView = VoiceCallView(callId ?: "", sessionId, aiSessionId, sipAddress, state)
}

/** Keeps technical call identity separate from TrainingSession.state. */
@Component
class VoiceCallRegistry {
    private val calls = ConcurrentHashMap<UUID, VoiceCallContext>()

    @Synchronized
    fun reserve(sessionId: UUID, aiSessionId: String, sipAddress: String) {
        if (calls.containsKey(sessionId)) throw IllegalStateException("Для сессии $sessionId звонок уже создан")
        calls[sessionId] = VoiceCallContext(sessionId, aiSessionId, sipAddress)
    }

    @Synchronized
    fun bind(handle: MediaCallHandle): VoiceCallView {
        val context = require(handle.sessionId)
        if (context.callId != null && context.callId != handle.callId) {
            throw UpstreamProtocolException("Media Gateway вернул другой callId")
        }
        context.callId = handle.callId
        if (context.state == "STARTING") context.state = handle.state
        return context.toView()
    }

    @Synchronized
    fun validate(event: SessionEvent): VoiceCallView {
        val context = require(event.sessionId)
        val eventCallId = event.payload["callId"] as? String
        if (eventCallId.isNullOrBlank()) throw IllegalArgumentException("Media-событие не содержит callId")
        if (context.callId != null && context.callId != eventCallId) {
            throw IllegalStateException("callId не принадлежит учебной сессии")
        }
        val eventAiId = event.payload["aiSessionId"] as? String
        if (eventAiId != null && eventAiId != context.aiSessionId) {
            throw IllegalStateException("aiSessionId не принадлежит учебной сессии")
        }
        context.callId = eventCallId
        return context.toView()
    }

    @Synchronized
    fun update(sessionId: UUID, state: String): VoiceCallView = require(sessionId).let {
        it.state = state
        it.toView()
    }

    @Synchronized
    fun get(sessionId: UUID): VoiceCallView = require(sessionId).toView()

    @Synchronized
    fun cancelUnbound(sessionId: UUID) {
        if (calls[sessionId]?.callId == null) calls.remove(sessionId)
    }

    @Synchronized
    fun takeAiSessionForClose(sessionId: UUID): String? = require(sessionId).let {
        if (it.aiClosed) null else {
            it.aiClosed = true
            it.aiSessionId
        }
    }

    private fun require(sessionId: UUID): VoiceCallContext = calls[sessionId]
        ?: throw NoSuchElementException("Звонок для сессии $sessionId не найден")
}

@Service
class VoiceTrainingService(
    private val sessions: TrainingSessionRepository,
    private val sessionService: TrainingSessionService,
    private val events: SessionEventRepository,
    private val aiClient: AiClient,
    private val mediaClient: MediaClient,
    private val calls: VoiceCallRegistry
) {
    fun start(sessionId: UUID, sipAddress: String): VoiceCallView {
        val destination = sipAddress.trim()
        require(SIP_ADDRESS.matches(destination)) { "Допустим SIP-адрес вида 1001 или PJSIP/1001" }
        val session = requireVoiceSession(sessionId)
        if (session.state !in setOf(SessionState.CREATED, SessionState.READY)) {
            throw IllegalStateException("Звонок нельзя начать в состоянии ${session.state}")
        }
        val ai = aiClient.createSession(sessionId, session.scenario)
        if (session.state == SessionState.CREATED) sessionService.markReady(sessionId)
        calls.reserve(sessionId, ai.aiSessionId, destination)
        return try {
            calls.bind(mediaClient.startCall(MediaCallCommand(sessionId, ai.aiSessionId, destination)))
        } catch (exception: Exception) {
            calls.cancelUnbound(sessionId)
            throw exception
        }
    }

    fun hangup(sessionId: UUID): VoiceCallView {
        requireVoiceSession(sessionId)
        val current = calls.get(sessionId)
        if (current.state == "ENDED" || current.state == "FAILED") return current
        if (current.callId.isBlank()) throw IllegalStateException("Media ещё не выдал callId")
        val response = mediaClient.hangup(current.callId, sessionId)
        return calls.update(sessionId, response.state)
    }

    fun getCall(sessionId: UUID): VoiceCallView {
        requireVoiceSession(sessionId)
        return calls.get(sessionId)
    }

    fun events(sessionId: UUID): List<SessionEvent> {
        requireVoiceSession(sessionId)
        return events.findBySessionId(sessionId)
    }

    fun receive(event: SessionEvent): Boolean {
        if (event.source != EventSource.MEDIA.value) throw IllegalArgumentException("Источник события должен быть media")
        if (event.type !in MEDIA_TYPES) throw IllegalArgumentException("Неподдерживаемое Media-событие ${event.type}")
        requireVoiceSession(event.sessionId)
        calls.validate(event)
        val accepted = sessionService.applyMediaEvent(event)
        if (accepted) {
            val sessionState = requireVoiceSession(event.sessionId).state
            when (event.type) {
                SessionEventType.CALL_RINGING.value -> if (sessionState == SessionState.RINGING) {
                    calls.update(event.sessionId, "RINGING")
                }
                SessionEventType.CALL_ANSWERED.value -> if (sessionState == SessionState.ACTIVE) {
                    calls.update(event.sessionId, "ACTIVE")
                }
                SessionEventType.CALL_ENDED.value, SessionEventType.MEDIA_ERROR.value,
                SessionEventType.SYSTEM_ERROR.value -> {
                    if (sessionState in setOf(SessionState.COMPLETED, SessionState.FAILED)) {
                        calls.update(event.sessionId, if (sessionState == SessionState.COMPLETED) "ENDED" else "FAILED")
                        calls.takeAiSessionForClose(event.sessionId)?.let(aiClient::closeSession)
                    }
                }
            }
        }
        return accepted
    }

    private fun requireVoiceSession(sessionId: UUID) = sessions.findById(sessionId)?.also {
        if (it.mode != SessionMode.VOICE) throw IllegalStateException("Сессия $sessionId не является голосовой")
    } ?: throw NoSuchElementException("Учебная сессия $sessionId не найдена")

    private companion object {
        val SIP_ADDRESS = Regex("(?:PJSIP/)?[A-Za-z0-9_.-]{1,64}")
        val MEDIA_TYPES = setOf(
            SessionEventType.CALL_RINGING.value, SessionEventType.CALL_ANSWERED.value,
            SessionEventType.CALL_ENDED.value, SessionEventType.MEDIA_ERROR.value,
            SessionEventType.MEDIA_LATENCY.value, SessionEventType.SYSTEM_ERROR.value,
            SessionEventType.TRANSCRIPT_PARTIAL.value, SessionEventType.TRANSCRIPT_FINAL.value,
            SessionEventType.OPERATOR_SPEECH_STARTED.value, SessionEventType.OPERATOR_SPEECH_ENDED.value,
            SessionEventType.CALLER_INTERRUPTED.value
        )
    }
}
