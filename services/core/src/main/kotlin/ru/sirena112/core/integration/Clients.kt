package ru.sirena112.core.integration

import java.util.UUID
import java.util.concurrent.ConcurrentHashMap

data class AiSessionHandle(val aiSessionId: String)

data class MediaCallCommand(
    val sessionId: UUID,
    val aiSessionId: String,
    val destination: String
)

data class MediaCallHandle(val sessionId: UUID, val started: Boolean)

/**
 * Контракт Core -> Python AI.
 *
 * Оценивание вынесено в AI намеренно: там лежат рубрика, разбор транскрипта
 * и человеческие объяснения. Core остаётся источником истины по классификации
 * и маршрутизации и передаёт свой расчёт готовым.
 */
interface AiClient {
    fun createSession(sessionId: UUID, scenarioId: UUID): AiSessionHandle

    /**
     * Просит AI оценить занятие.
     *
     * Возвращает null, если AI недоступен или ответил непонятно. Это не ошибка
     * занятия: карточка обучающегося уже сохранена, и Core считает упрощённый
     * отчёт сам. Демонстрация не должна падать из-за выключенного сервиса.
     */
    fun score(command: AiScoreCommand): AiScoreReport?
}

/** Контракт Core -> Go Media. Реальная REST/WebSocket-интеграция подключается позже. */
interface MediaClient {
    fun startCall(command: MediaCallCommand): MediaCallHandle
    fun hangup(sessionId: UUID): MediaCallHandle
}

/** Заглушка для тестов и запуска без AI: оценку не считает. */
class MockAiClient : AiClient {
    private val sessions = ConcurrentHashMap<UUID, AiSessionHandle>()

    override fun createSession(sessionId: UUID, scenarioId: UUID): AiSessionHandle =
        sessions.computeIfAbsent(sessionId) { AiSessionHandle("mock-ai-$sessionId") }

    override fun score(command: AiScoreCommand): AiScoreReport? = null
}

/** Заглушка телефонии для запуска без Media. */
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
