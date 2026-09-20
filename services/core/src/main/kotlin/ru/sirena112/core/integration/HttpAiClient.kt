package ru.sirena112.core.integration

import org.slf4j.LoggerFactory
import org.springframework.web.client.RestTemplate
import ru.sirena112.core.config.CoreProperties
import java.util.UUID
import java.util.concurrent.ConcurrentHashMap

/**
 * HTTP-клиент к Python AI.
 *
 * Правило одно: ни одна проблема AI не должна ломать занятие. Сервис выключен,
 * отвечает медленно или отдал неожиданный формат - клиент возвращает null,
 * а Core показывает свой упрощённый отчёт. Карточка обучающегося при этом
 * уже сохранена и не теряется.
 */
class HttpAiClient(
    private val restTemplate: RestTemplate,
    private val properties: CoreProperties
) : AiClient {

    private val log = LoggerFactory.getLogger(HttpAiClient::class.java)
    private val sessions = ConcurrentHashMap<UUID, AiSessionHandle>()

    override fun createSession(sessionId: UUID, scenarioId: UUID): AiSessionHandle =
        sessions.computeIfAbsent(sessionId) { AiSessionHandle("ai-$sessionId") }

    override fun score(command: AiScoreCommand): AiScoreReport? {
        val baseUrl = properties.aiBaseUrl.trimEnd('/')
        if (baseUrl.isBlank()) {
            return null
        }

        return try {
            restTemplate.postForObject(
                "$baseUrl/ai/sessions/score",
                command,
                AiScoreReport::class.java
            )
        } catch (exception: Exception) {
            // Уровень warn, а не error: это ожидаемый режим работы без AI.
            log.warn(
                "AI не оценил сессию {}: {}. Используется упрощённый отчёт Core.",
                command.sessionId,
                exception.message
            )
            null
        }
    }
}
