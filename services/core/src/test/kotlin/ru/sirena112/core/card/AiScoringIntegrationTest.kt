package ru.sirena112.core.card

import com.fasterxml.jackson.databind.JsonNode
import com.fasterxml.jackson.databind.ObjectMapper
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import org.springframework.beans.factory.annotation.Autowired
import org.springframework.boot.test.context.SpringBootTest
import org.springframework.boot.test.context.TestConfiguration
import org.springframework.context.annotation.Bean
import org.springframework.context.annotation.Primary
import ru.sirena112.core.integration.AiClient
import ru.sirena112.core.integration.AiCriterion
import ru.sirena112.core.integration.AiError
import ru.sirena112.core.integration.AiPenalty
import ru.sirena112.core.integration.AiScoreCommand
import ru.sirena112.core.integration.AiScoreReport
import ru.sirena112.core.integration.AiSessionHandle
import java.nio.file.Paths
import java.util.UUID

/**
 * Оценку считает AI, а Core только сохраняет результат. Здесь проверяется
 * и это, и обратный случай: при недоступном AI занятие не должно ломаться.
 */
@SpringBootTest
class AiScoringIntegrationTest {

    /** Подменяет настоящий HTTP-клиент: сеть в тестах не нужна. */
    class StubAiClient : AiClient {
        var lastCommand: AiScoreCommand? = null
        var report: AiScoreReport? = null

        override fun createSession(sessionId: UUID, scenarioId: UUID): AiSessionHandle =
            AiSessionHandle("stub-$sessionId")

        override fun score(command: AiScoreCommand): AiScoreReport? {
            lastCommand = command
            return report
        }
    }

    @TestConfiguration
    class StubConfiguration {
        // Один бин и на роль AiClient, и для настройки из теста: два главных
        // кандидата одного типа контекст не соберут.
        @Bean
        @Primary
        fun stubAiClient(): StubAiClient = StubAiClient()
    }

    @Autowired
    lateinit var facade: CardTrainingFacade

    @Autowired
    lateinit var stub: StubAiClient

    @Autowired
    lateinit var objectMapper: ObjectMapper

    private fun submitSession(): SessionReport {
        val session = facade.createSession(
            CreateCardSessionRequest(scenarioId = CardTrainingFacade.DEFAULT_SCENARIO_ID)
        )
        facade.start(session.id)
        return facade.submit(session.id, SubmitCardRequest(input = expectedInput()))
    }

    private fun expectedInput(): ru.sirena112.core.classifier.OperatorCardInput {
        val node: JsonNode = objectMapper.readTree(
            repoRoot().resolve(Paths.get("contracts", "examples", "scenario-1050602.json")).toFile()
        ).at("/groundTruth/expectedInput")
        return objectMapper.treeToValue(node, ru.sirena112.core.classifier.OperatorCardInput::class.java)
    }

    private fun repoRoot(): java.nio.file.Path {
        var dir = Paths.get("").toAbsolutePath()
        repeat(8) {
            if (java.nio.file.Files.isDirectory(dir.resolve("contracts"))) return dir
            dir = dir.parent ?: return dir
        }
        return dir
    }

    @Test
    fun `отчёт берётся у AI вместе с объяснениями`() {
        stub.report = AiScoreReport(
            sessionId = "any",
            classifierVersion = "046-2024-11-15",
            totalScore = 87.5,
            maxScore = 100.0,
            passed = true,
            criteria = listOf(
                AiCriterion("SIGNS", "Выбрал полный путь признаков", 30.0, 30.0, "PASSED"),
                AiCriterion("ADDRESS", "Собрал адрес", 30.0, 15.0, "PARTIAL")
            ),
            errors = listOf(
                AiError("CRITERION_ADDRESS", "Не указан подъезд", "OPERATOR", "MAJOR", "address")
            ),
            penalties = listOf(AiPenalty("TIME_LIMIT_EXCEEDED", "Норматив превышен", 10.0)),
            recommendations = listOf("Уточняйте адрес до подъезда")
        )

        val report = submitSession()

        assertEquals(87.5, report.score)
        assertTrue(report.passed)
        assertEquals(setOf("SIGNS", "ADDRESS"), report.criteria.map { it.code }.toSet())
        // Штраф AI не теряется: в модели Core для него нет отдельного места,
        // поэтому он переносится в ошибки.
        assertTrue(report.errors.any { it.code == "TIME_LIMIT_EXCEEDED" })
        assertEquals(listOf("Уточняйте адрес до подъезда"), report.recommendations)
    }

    @Test
    fun `AI получает сценарий, карточку и расчёт Core`() {
        stub.report = null

        submitSession()
        val command = requireNotNull(stub.lastCommand)

        assertEquals("1050602", command.scenario.groundTruth.classifierCode)
        assertEquals("1050602", command.calculation?.classifierCode)
        assertTrue(command.submittedCard.incident?.selectedSignIds?.isNotEmpty() == true)
    }

    @Test
    fun `при недоступном AI занятие не ломается`() {
        stub.report = null

        val report = submitSession()

        assertTrue(report.maxScore > 0.0)
        assertEquals("1050602", report.classifierCode)
    }
}
