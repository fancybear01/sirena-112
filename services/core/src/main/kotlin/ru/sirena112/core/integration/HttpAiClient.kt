package ru.sirena112.core.integration

import com.fasterxml.jackson.databind.JsonNode
import org.slf4j.LoggerFactory
import org.slf4j.MDC
import org.springframework.http.HttpEntity
import org.springframework.http.HttpHeaders
import org.springframework.http.HttpMethod
import org.springframework.http.MediaType
import org.springframework.web.client.HttpStatusCodeException
import org.springframework.web.client.ResourceAccessException
import org.springframework.web.client.RestClientException
import org.springframework.web.client.RestTemplate
import ru.sirena112.core.config.CoreProperties
import ru.sirena112.core.domain.Scenario
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

    override fun createSession(sessionId: UUID, scenario: Scenario): AiSessionHandle =
        sessions.computeIfAbsent(sessionId) {
            val baseUrl = properties.aiBaseUrl.trimEnd('/')
            if (baseUrl.isBlank()) throw UpstreamUnavailableException("AI не настроен для голосовой сессии")
            val headers = HttpHeaders().apply {
                contentType = MediaType.APPLICATION_JSON
                set("X-Request-ID", MDC.get("requestId") ?: UUID.randomUUID().toString())
                System.getenv("AI_SERVICE_TOKEN")?.takeIf { it.isNotBlank() }?.let { setBearerAuth(it) }
            }
            val response = try {
                restTemplate.exchange(
                    "$baseUrl/ai/voice/sessions",
                    HttpMethod.POST,
                    HttpEntity(mapOf("sessionId" to sessionId.toString(), "scenario" to scenario), headers),
                    JsonNode::class.java
                ).body
            } catch (exception: ResourceAccessException) {
                throw UpstreamUnavailableException("AI недоступен для голосовой сессии", exception)
            } catch (exception: HttpStatusCodeException) {
                if (exception.statusCode.is5xxServerError) {
                    throw UpstreamUnavailableException("AI не может создать голосовую сессию", exception)
                }
                throw UpstreamProtocolException("AI отклонил голосовую сессию: HTTP ${exception.rawStatusCode}", exception)
            } catch (exception: RestClientException) {
                throw UpstreamProtocolException("Некорректный ответ AI при создании голосовой сессии", exception)
            }
            val aiSessionId = response?.path("aiSessionId")?.asText().orEmpty()
            if (aiSessionId.isBlank() || response?.path("sessionId")?.asText() != sessionId.toString() ||
                response?.path("scenarioId")?.asText() != scenario.id.toString()) {
                throw UpstreamProtocolException("AI вернул идентификаторы другой голосовой сессии")
            }
            AiSessionHandle(aiSessionId)
        }

    override fun closeSession(aiSessionId: String) {
        sessions.entries.removeIf { it.value.aiSessionId == aiSessionId }
        val baseUrl = properties.aiBaseUrl.trimEnd('/')
        if (baseUrl.isBlank()) return
        runCatching { restTemplate.exchange("$baseUrl/ai/voice/sessions/$aiSessionId", HttpMethod.DELETE,
            HttpEntity<Void>(serviceHeaders()), Void::class.java) }
            .onFailure { log.warn("Не удалось освободить голосовую AI-сессию {}: {}", aiSessionId, it.message) }
    }

    override fun score(command: AiScoreCommand): AiScoreReport? {
        val baseUrl = properties.aiBaseUrl.trimEnd('/')
        if (baseUrl.isBlank()) {
            return null
        }

        return try {
            restTemplate.exchange("$baseUrl/ai/sessions/score", HttpMethod.POST,
                HttpEntity(command, serviceHeaders()), AiScoreReport::class.java).body
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

    private fun serviceHeaders(): HttpHeaders = HttpHeaders().apply {
        contentType = MediaType.APPLICATION_JSON
        System.getenv("AI_SERVICE_TOKEN")?.takeIf { it.isNotBlank() }?.let { setBearerAuth(it) }
    }
}
