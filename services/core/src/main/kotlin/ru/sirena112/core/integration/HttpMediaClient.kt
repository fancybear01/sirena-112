package ru.sirena112.core.integration

import com.fasterxml.jackson.databind.JsonNode
import org.slf4j.MDC
import org.springframework.http.HttpEntity
import org.springframework.http.HttpHeaders
import org.springframework.http.HttpMethod
import org.springframework.http.HttpStatus
import org.springframework.http.MediaType
import org.springframework.web.client.HttpStatusCodeException
import org.springframework.web.client.ResourceAccessException
import org.springframework.web.client.RestClientException
import org.springframework.web.client.RestTemplate
import ru.sirena112.core.config.CoreProperties
import java.net.SocketTimeoutException
import java.util.UUID

/** HTTP adapter for the command contract in contracts/media-core.md. */
class HttpMediaClient(
    private val restTemplate: RestTemplate,
    private val properties: CoreProperties
) : MediaClient {
    override fun startCall(command: MediaCallCommand): MediaCallHandle {
        val response = post(
            "/internal/v1/calls/start",
            mapOf("sessionId" to command.sessionId.toString(),
                "aiSessionId" to command.aiSessionId, "sipAddress" to command.destination),
            HttpStatus.ACCEPTED
        )
        return handle(response, command.sessionId, command.aiSessionId, command.destination,
            setOf("RINGING", "ACTIVE", "ENDED", "FAILED"))
    }

    override fun hangup(callId: String, sessionId: UUID): MediaCallHandle {
        val response = post(
            "/internal/v1/calls/hangup",
            mapOf("callId" to callId, "sessionId" to sessionId.toString()),
            HttpStatus.OK
        )
        return handle(response, sessionId, "", "", setOf("ENDED"), callId)
    }

    private fun post(path: String, body: Map<String, String>, expectedStatus: HttpStatus): JsonNode {
        val baseUrl = properties.mediaBaseUrl.trimEnd('/')
        if (baseUrl.isBlank()) throw UpstreamUnavailableException("Media Gateway не настроен")
        val headers = HttpHeaders().apply {
            contentType = MediaType.APPLICATION_JSON
            set("X-Request-ID", MDC.get("requestId") ?: UUID.randomUUID().toString())
            System.getenv("CORE_MEDIA_SERVICE_TOKEN")?.takeIf { it.isNotBlank() }?.let { setBearerAuth(it) }
        }
        val response = try {
            restTemplate.exchange(
                "$baseUrl$path", HttpMethod.POST, HttpEntity(body, headers), JsonNode::class.java
            )
        } catch (exception: ResourceAccessException) {
            val timedOut = generateSequence(exception as Throwable?) { it.cause }
                .any { it is SocketTimeoutException }
            throw UpstreamUnavailableException(
                if (timedOut) "Media Gateway не ответил вовремя; проверьте состояние звонка перед повтором"
                else "Media Gateway недоступен", exception
            )
        } catch (exception: HttpStatusCodeException) {
            when (exception.rawStatusCode) {
                409 -> throw UpstreamConflictException("Media Gateway: звонок уже активен", exception)
                503 -> throw UpstreamUnavailableException(
                    if (exception.responseBodyAsString.contains("\"capacity_exhausted\""))
                        "Media Gateway перегружен: нет свободных RTP-портов"
                    else "Media Gateway не готов: проверьте Asterisk/ARI", exception
                )
                else -> throw UpstreamProtocolException(
                    "Media Gateway отклонил команду: HTTP ${exception.rawStatusCode}", exception
                )
            }
        } catch (exception: RestClientException) {
            throw UpstreamProtocolException("Некорректный ответ Media Gateway", exception)
        }
        if (response.statusCode != expectedStatus || response.body == null) {
            throw UpstreamProtocolException("Media Gateway вернул неожиданный ответ на $path")
        }
        return response.body!!
    }

    private fun handle(
        response: JsonNode,
        sessionId: UUID,
        aiSessionId: String,
        sipAddress: String,
        expectedStates: Set<String>,
        expectedCallId: String? = null
    ): MediaCallHandle {
        val callId = response.path("callId").asText()
        val state = response.path("state").asText()
        if (callId.isBlank() || response.path("sessionId").asText() != sessionId.toString() ||
            state !in expectedStates || (expectedCallId != null && callId != expectedCallId) ||
            (aiSessionId.isNotBlank() && response.path("aiSessionId").asText() != aiSessionId) ||
            (sipAddress.isNotBlank() && response.path("sipAddress").asText() != sipAddress)
        ) {
            throw UpstreamProtocolException("Media Gateway вернул звонок другой сессии или неверное состояние")
        }
        return MediaCallHandle(callId, sessionId, aiSessionId, sipAddress, state)
    }
}
