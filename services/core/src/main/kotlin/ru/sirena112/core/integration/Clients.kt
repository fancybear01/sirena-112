package ru.sirena112.core.integration

import org.springframework.stereotype.Service
import java.util.UUID
import java.util.concurrent.ConcurrentHashMap

data class AiSessionHandle(val aiSessionId: String)

data class MediaCallCommand(
    val sessionId: UUID,
    val aiSessionId: String,
    val destination: String
)

data class MediaCallHandle(val sessionId: UUID, val started: Boolean)

/** Контракт Core -> Python AI. Реальная HTTP-интеграция подключается позже. */
interface AiClient {
    fun createSession(sessionId: UUID, scenarioId: UUID): AiSessionHandle
}

/** Контракт Core -> Go Media. Реальная REST/WebSocket-интеграция подключается позже. */
interface MediaClient {
    fun startCall(command: MediaCallCommand): MediaCallHandle
    fun hangup(sessionId: UUID): MediaCallHandle
}

@Service
class MockAiClient : AiClient {
    private val sessions = ConcurrentHashMap<UUID, AiSessionHandle>()

    override fun createSession(sessionId: UUID, scenarioId: UUID): AiSessionHandle =
        sessions.computeIfAbsent(sessionId) { AiSessionHandle("mock-ai-$sessionId") }
}

@Service
class MockMediaClient : MediaClient {
    private val calls = ConcurrentHashMap<UUID, MediaCallCommand>()

    override fun startCall(command: MediaCallCommand): MediaCallHandle {
        calls[command.sessionId] = command
        return MediaCallHandle(command.sessionId, started = true)
    }

    override fun hangup(sessionId: UUID): MediaCallHandle {
        calls.remove(sessionId)
        return MediaCallHandle(sessionId, started = false)
    }
}
