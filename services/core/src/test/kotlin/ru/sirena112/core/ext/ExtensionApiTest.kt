package ru.sirena112.core.ext

import com.fasterxml.jackson.module.kotlin.jacksonObjectMapper
import org.assertj.core.api.Assertions.assertThat
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.assertThrows
import org.springframework.http.HttpStatus
import org.springframework.mock.web.MockFilterChain
import org.springframework.mock.web.MockHttpServletRequest
import org.springframework.mock.web.MockHttpServletResponse
import org.springframework.web.server.ResponseStatusException
import ru.sirena112.core.card.CriterionScore
import ru.sirena112.core.card.InMemorySessionReportRepository
import ru.sirena112.core.card.SessionReport
import ru.sirena112.core.classifier.CardScenarioFixtures
import ru.sirena112.core.domain.InMemoryScenarioRepository
import ru.sirena112.core.domain.InMemorySessionEventRepository
import ru.sirena112.core.domain.InMemoryTrainingSessionRepository
import ru.sirena112.core.domain.Scenario
import ru.sirena112.core.domain.SessionEvent
import ru.sirena112.core.domain.SessionMode
import ru.sirena112.core.domain.TrainingSession
import java.nio.file.Path
import java.util.UUID

/**
 * Контракт API расширений. Задача #97.
 *
 * Проверяется то, на что будет опираться сторонний модуль, и то, чего он
 * не должен получить ни при каких условиях: личных данных и возможности
 * изменить что-либо.
 */
class ExtensionApiTest {
    private val mapper = jacksonObjectMapper()
    private val scenario: Scenario = CardScenarioFixtures(mapper)
        .load(Path.of("../../contracts/examples/scenario-1050602.json"))

    private fun controller(
        sessionCount: Int = 0,
        withReport: Boolean = false
    ): Triple<ExtensionApiController, InMemoryTrainingSessionRepository, InMemorySessionReportRepository> {
        val scenarios = InMemoryScenarioRepository().also { it.save(scenario) }
        val sessions = InMemoryTrainingSessionRepository()
        val reports = InMemorySessionReportRepository()
        val events = InMemorySessionEventRepository()
        repeat(sessionCount) {
            val session = TrainingSession(UUID.randomUUID(), scenario, SessionMode.CARD,
                groupId = UUID.randomUUID())
            sessions.save(session)
            if (withReport) {
                reports.save(SessionReport(session.id, 75.0, 100.0, false,
                    listOf(CriterionScore("ADDRESS", true, 20.0, 20.0, "Адрес собран")),
                    emptyList(), listOf("Повторить сбор адреса"),
                    scenario.groundTruth.classifierVersion, scenario.groundTruth.classifierCode))
            }
        }
        return Triple(ExtensionApiController(scenarios, sessions, reports, events), sessions, reports)
    }

    private fun request(): MockHttpServletRequest =
        MockHttpServletRequest().also { it.setAttribute("requestId", "req-1") }

    // --- что отдаётся ---------------------------------------------------------

    @Test fun `meta announces read-only surface and its limits`() {
        val (api, _, _) = controller()

        val meta = api.meta(request())

        assertThat(meta.apiVersion).isEqualTo("v1")
        assertThat(meta.readOnly).isTrue
        assertThat(meta.maxPageSize).isEqualTo(EXT_MAX_PAGE_SIZE)
        assertThat(meta.limitations).isNotEmpty
        assertThat(meta.requestId).isEqualTo("req-1")
    }

    @Test fun `scenarios expose classification but not the expected answer`() {
        val (api, _, _) = controller()

        val page = api.scenarios(0, 50, request())

        assertThat(page.items).hasSize(1)
        val json = mapper.writeValueAsString(page.items)
        assertThat(json).contains("classifierCode", "incidentType", "difficulty")
        // expectedInput - это ответ на задание. Расширению он не нужен,
        // а утечка сделала бы возможной подсказку обучающемуся.
        assertThat(json).doesNotContain("expectedInput", "requiredServices", "mainServices")
    }

    @Test fun `sessions do not expose the card or the student`() {
        val (api, _, _) = controller(sessionCount = 2)

        val json = mapper.writeValueAsString(api.sessions(0, 50, null, request()).items)

        assertThat(json).contains("scenarioId", "state", "groupId")
        for (forbidden in listOf("studentId", "teacherId", "card", "operatorCard",
                "submittedCard", "description", "displayName", "studentName", "phone")) {
            assertThat(json).doesNotContain(forbidden)
        }
    }

    @Test fun `result exposes scores without the human-facing text`() {
        val (api, sessions, _) = controller(sessionCount = 1, withReport = true)
        val sessionId = sessions.findAll().first().id

        val result = api.result(sessionId, request())

        assertThat(result.totalScore).isEqualTo(75.0)
        assertThat(result.maxScore).isEqualTo(100.0)
        assertThat(result.passed).isFalse
        assertThat(result.criteria.map { it.code }).containsExactly("ADDRESS")
        val json = mapper.writeValueAsString(result)
        // Формулировки критериев и рекомендации - текст для человека. Он
        // меняется без смены версии API, поэтому в контракт не входит.
        assertThat(json).doesNotContain("Адрес собран", "Повторить сбор адреса", "message")
    }

    @Test fun `events expose type and time but not payload`() {
        val scenarios = InMemoryScenarioRepository().also { it.save(scenario) }
        val sessions = InMemoryTrainingSessionRepository()
        val events = InMemorySessionEventRepository()
        val session = TrainingSession(UUID.randomUUID(), scenario, SessionMode.VOICE)
        sessions.save(session)
        events.saveIfAbsent(SessionEvent(UUID.randomUUID(), session.id, "transcript.final",
            java.time.Instant.now(), "ai", mapOf("text" to "секретный транскрипт")))
        val api = ExtensionApiController(scenarios, sessions, InMemorySessionReportRepository(), events)

        val json = mapper.writeValueAsString(api.events(session.id, 0, 50, request()).items)

        assertThat(json).contains("transcript.final")
        // Полезная нагрузка может содержать речь обучающегося - её не отдаём.
        assertThat(json).doesNotContain("секретный транскрипт", "payload")
    }

    // --- постраничная выдача --------------------------------------------------

    @Test fun `page size is capped so one call cannot ask for everything`() {
        val (api, _, _) = controller(sessionCount = 5)

        val page = api.sessions(0, 100_000, null, request())

        assertThat(page.size).isEqualTo(EXT_MAX_PAGE_SIZE)
        assertThat(page.total).isEqualTo(5)
    }

    @Test fun `paging walks the whole list without repeating`() {
        val (api, _, _) = controller(sessionCount = 5)

        val first = api.sessions(0, 2, null, request())
        val second = api.sessions(1, 2, null, request())
        val third = api.sessions(2, 2, null, request())

        assertThat(first.items).hasSize(2)
        assertThat(second.items).hasSize(2)
        assertThat(third.items).hasSize(1)
        val seen = (first.items + second.items + third.items).map { it.id }
        assertThat(seen).doesNotHaveDuplicates().hasSize(5)
    }

    @Test fun `page past the end is empty, not an error`() {
        val (api, _, _) = controller(sessionCount = 2)

        val page = api.sessions(99, 10, null, request())

        assertThat(page.items).isEmpty()
        assertThat(page.total).isEqualTo(2)
    }

    @Test fun `negative page and zero size are refused`() {
        val (api, _, _) = controller(sessionCount = 1)

        assertThat(assertThrows<ResponseStatusException> { api.sessions(-1, 10, null, request()) }.status)
            .isEqualTo(HttpStatus.BAD_REQUEST)
        assertThat(assertThrows<ResponseStatusException> { api.sessions(0, 0, null, request()) }.status)
            .isEqualTo(HttpStatus.BAD_REQUEST)
    }

    @Test fun `sessions can be filtered by state`() {
        val (api, _, _) = controller(sessionCount = 3)

        assertThat(api.sessions(0, 50, "CREATED", request()).total).isEqualTo(3)
        assertThat(api.sessions(0, 50, "SCORED", request()).total).isEqualTo(0)
    }

    // --- отказы ---------------------------------------------------------------

    @Test fun `result of a session without a report is not found`() {
        val (api, _, _) = controller(sessionCount = 1)
        val sessionId = api.sessions(0, 1, null, request()).items.first().id

        assertThat(assertThrows<ResponseStatusException> { api.result(sessionId, request()) }.status)
            .isEqualTo(HttpStatus.NOT_FOUND)
    }

    @Test fun `events of an unknown session are not found`() {
        val (api, _, _) = controller()

        assertThat(assertThrows<ResponseStatusException> {
            api.events(UUID.randomUUID(), 0, 10, request())
        }.status).isEqualTo(HttpStatus.NOT_FOUND)
    }

    // --- сервисный токен ------------------------------------------------------

    private fun pass(token: String, header: String?): MockHttpServletResponse {
        val request = MockHttpServletRequest()
        header?.let { request.addHeader("Authorization", it) }
        val response = MockHttpServletResponse()
        ExtensionTokenFilter(token).doFilter(request, response, MockFilterChain())
        return response
    }

    @Test fun `without a configured token the surface is closed, not open`() {
        // Самое важное в этом фильтре. Пустой токен мог бы означать
        // "проверять нечем, пускаем всех" - и защита выглядела бы работающей.
        assertThat(pass("", "Bearer whatever").status).isEqualTo(HttpStatus.SERVICE_UNAVAILABLE.value())
        assertThat(pass("", null).status).isEqualTo(HttpStatus.SERVICE_UNAVAILABLE.value())
    }

    @Test fun `wrong or missing token is refused`() {
        assertThat(pass("right-token", "Bearer wrong-token").status)
            .isEqualTo(HttpStatus.UNAUTHORIZED.value())
        assertThat(pass("right-token", null).status).isEqualTo(HttpStatus.UNAUTHORIZED.value())
        assertThat(pass("right-token", "right-token").status)
            .isEqualTo(HttpStatus.UNAUTHORIZED.value())
    }

    @Test fun `correct token passes through`() {
        assertThat(pass("right-token", "Bearer right-token").status).isEqualTo(HttpStatus.OK.value())
    }

    @Test fun `token with non-ascii characters does not break the check`() {
        // Заголовки HTTP переносят не всё, и сравнение по байтам не должно
        // падать на неожидаемом вводе - оно должно отказывать.
        assertThat(pass("правильный-токен", "Bearer другой").status)
            .isEqualTo(HttpStatus.UNAUTHORIZED.value())
        assertThat(pass("правильный-токен", "Bearer правильный-токен").status)
            .isEqualTo(HttpStatus.OK.value())
    }
}
