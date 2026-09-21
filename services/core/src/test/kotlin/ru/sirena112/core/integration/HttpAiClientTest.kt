package ru.sirena112.core.integration

import com.fasterxml.jackson.databind.ObjectMapper
import com.fasterxml.jackson.module.kotlin.registerKotlinModule
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import org.springframework.http.MediaType
import org.springframework.test.web.client.MockRestServiceServer
import org.springframework.test.web.client.match.MockRestRequestMatchers.method
import org.springframework.test.web.client.match.MockRestRequestMatchers.requestTo
import org.springframework.test.web.client.response.MockRestResponseCreators.withServerError
import org.springframework.test.web.client.response.MockRestResponseCreators.withSuccess
import org.springframework.http.HttpMethod
import org.springframework.web.client.RestTemplate
import ru.sirena112.core.classifier.CalculationStatus
import ru.sirena112.core.classifier.CardCalculation
import ru.sirena112.core.classifier.OperatorCardInput
import ru.sirena112.core.domain.Difficulty
import ru.sirena112.core.domain.GroundTruth
import ru.sirena112.core.domain.Rubric
import ru.sirena112.core.domain.RubricCriterion
import ru.sirena112.core.domain.Scenario
import ru.sirena112.core.domain.ScenarioCategory
import ru.sirena112.core.classifier.ResponseScenarioStatus
import ru.sirena112.core.classifier.ServiceRef
import ru.sirena112.core.config.CoreProperties
import java.util.UUID

/**
 * Клиент к AI обязан быть безопасным для занятия: любая проблема сервиса
 * превращается в null, а не в исключение. Отчёт Core в этом случае считает сам.
 */
class HttpAiClientTest {

    private val properties = CoreProperties(aiBaseUrl = "http://ai.test")
    private val restTemplate = RestTemplate().apply {
        messageConverters.add(
            org.springframework.http.converter.json.MappingJackson2HttpMessageConverter(
                ObjectMapper().registerKotlinModule()
            )
        )
    }
    private val server: MockRestServiceServer = MockRestServiceServer.createServer(restTemplate)
    private val client = HttpAiClient(restTemplate, properties)

    private fun command() = AiScoreCommand(
        sessionId = UUID.randomUUID().toString(),
        scenario = scenario(),
        submittedCard = OperatorCardInput(),
        calculation = CardCalculation(
            status = CalculationStatus.RESOLVED,
            classifierVersion = "046-2024-11-15",
            classifierCode = "1050602"
        ),
        elapsedSeconds = 25
    )

    private fun scenario() = Scenario(
        id = UUID.randomUUID(),
        version = 1,
        title = "задымление: мусоропровод",
        category = ScenarioCategory.FIRE,
        difficulty = Difficulty.BASIC,
        profile = "Учебный",
        groundTruth = GroundTruth(
            classifierVersion = "046-2024-11-15",
            classifierCode = "1050602",
            incidentType = "задымление: мусоропровод",
            ekp35IncidentType = "пожар: мусоропровод",
            responseScenarioCode = "1_9",
            responseScenarioStatus = ResponseScenarioStatus.CODE,
            mainServices = listOf(ServiceRef("MCHS", "Служба 101 (МЧС)")),
            requiredServices = emptyList(),
            expectedInput = OperatorCardInput()
        ),
        rubric = Rubric(listOf(RubricCriterion("SIGNS", "Признаки", 1.0, true)))
    )

    @Test
    fun `отчёт AI разбирается целиком`() {
        server.expect(requestTo("http://ai.test/ai/sessions/score"))
            .andExpect(method(HttpMethod.POST))
            .andRespond(
                withSuccess(
                    """
                    {
                      "sessionId": "s-1",
                      "scenarioId": "80c14c89-f2b7-527a-bd6f-268cdc3d4a11",
                      "classifierVersion": "046-2024-11-15",
                      "totalScore": 82.5,
                      "maxScore": 100.0,
                      "passed": true,
                      "criteria": [
                        {"code":"SIGNS","description":"Признаки","weight":3.0,
                         "maxPoints":30.0,"earnedPoints":30.0,"status":"PASSED"}
                      ],
                      "errors": [
                        {"code":"CRITERION_ADDRESS","kind":"OPERATOR","severity":"MAJOR",
                         "message":"Адрес неполный","field":"address.displayAddress"}
                      ],
                      "penalties": [
                        {"code":"TIME_LIMIT_EXCEEDED","message":"Норматив превышен","points":10.0}
                      ],
                      "recommendations": ["Уточняйте адрес до подъезда"],
                      "meta": {"engine":"rules","version":"0.1.0","deterministic":true}
                    }
                    """.trimIndent(),
                    MediaType.APPLICATION_JSON
                )
            )

        val report = client.score(command())

        assertEquals(82.5, report?.totalScore)
        assertEquals(1, report?.criteria?.size)
        assertEquals("TIME_LIMIT_EXCEEDED", report?.penalties?.first()?.code)
        server.verify()
    }

    @Test
    fun `ошибка AI не роняет занятие`() {
        server.expect(requestTo("http://ai.test/ai/sessions/score")).andRespond(withServerError())

        assertNull(client.score(command()))
    }

    @Test
    fun `без адреса AI не вызывается`() {
        val disabled = HttpAiClient(restTemplate, CoreProperties(aiBaseUrl = ""))

        assertNull(disabled.score(command()))
    }

    @Test
    fun `идентификатор AI-сессии устойчив`() {
        val sessionId = UUID.randomUUID()
        val scenario = scenario()
        server.expect(requestTo("http://ai.test/ai/voice/sessions"))
            .andExpect(method(HttpMethod.POST))
            .andRespond(withSuccess(
                """{"aiSessionId":"voice-test-1","sessionId":"$sessionId","scenarioId":"${scenario.id}"}""",
                MediaType.APPLICATION_JSON
            ))

        val first = client.createSession(sessionId, scenario)
        val second = client.createSession(sessionId, scenario)

        assertEquals(first.aiSessionId, second.aiSessionId)
        assertEquals("voice-test-1", first.aiSessionId)
        server.verify()
    }
}
