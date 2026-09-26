package ru.sirena112.core.card

import org.assertj.core.api.Assertions.assertThat
import org.junit.jupiter.api.Test
import org.springframework.beans.factory.annotation.Autowired
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc
import org.springframework.boot.test.context.SpringBootTest
import org.springframework.test.annotation.DirtiesContext
import org.springframework.test.web.servlet.MockMvc
import org.springframework.test.web.servlet.get
import ru.sirena112.core.domain.InMemoryTrainingSessionRepository
import ru.sirena112.core.domain.OperatorCard
import ru.sirena112.core.domain.ScenarioRepository
import ru.sirena112.core.domain.SessionMode
import ru.sirena112.core.domain.SessionState
import ru.sirena112.core.domain.TrainingSession
import ru.sirena112.core.domain.TrainingSessionRepository
import java.time.Instant
import java.util.UUID
import java.util.concurrent.TimeUnit

@SpringBootTest
@AutoConfigureMockMvc
@DirtiesContext(classMode = DirtiesContext.ClassMode.BEFORE_CLASS)
class TrainingAnalyticsTest {
    @Autowired lateinit var mvc: MockMvc
    @Autowired lateinit var scenarios: ScenarioRepository
    @Autowired lateinit var sessions: TrainingSessionRepository
    @Autowired lateinit var reports: SessionReportRepository
    @Autowired lateinit var access: ru.sirena112.core.auth.SessionAccess

    @Test
    fun `empty set has zero counts and no invented average`() {
        val empty = TrainingAnalyticsController(InMemoryTrainingSessionRepository(), InMemorySessionReportRepository(), access).summary()
        assertThat(empty.completedSessions).isZero()
        assertThat(empty.averagePercent).isNull()
        assertThat(empty.medianPercent).isNull()
        assertThat(empty.scoreDistribution.map { it.count }).containsExactly(0, 0, 0, 0, 0)
        assertThat(empty.incidentTypes).isEmpty()
        assertThat(empty.topErrors).isEmpty()
        assertThat(empty.daily).isEmpty()
    }

    @Test
    fun `summary counts only scored reports once and never exposes session data`() {
        val first = scenarios.findAll().first()
        val second = scenarios.findAll().first { it.groundTruth.classifierCode != first.groundTruth.classifierCode }
        val dayOne = Instant.parse("2026-09-24T10:00:00Z")
        val dayTwo = Instant.parse("2026-09-25T10:00:00Z")
        val one = saveSession(first, SessionState.SCORED, dayOne)
        val two = saveSession(first, SessionState.SCORED, dayOne.plusSeconds(60))
        val three = saveSession(second, SessionState.SCORED, dayTwo)
        val incomplete = saveSession(second, SessionState.COMPLETED, dayTwo)
        val missingReport = saveSession(first, SessionState.SCORED, dayTwo)
        val low = report(one, 20.0, "ADDRESS", "SERVICES")
        reports.save(low)
        reports.save(low) // upsert/re-score must not duplicate the session
        reports.save(report(two, 60.0, "ADDRESS"))
        reports.save(report(three, 100.0))
        reports.save(report(incomplete, 0.0, "ADDRESS"))

        val started = System.nanoTime()
        val firstResponse = mvc.get("/api/teacher/analytics/summary")
            .andExpect { status { isOk() } }
            .andReturn().response.contentAsString
        assertThat(TimeUnit.NANOSECONDS.toSeconds(System.nanoTime() - started)).isLessThan(30)
        val repeated = mvc.get("/api/teacher/analytics/summary")
            .andExpect { status { isOk() } }
            .andReturn().response.contentAsString
        assertThat(repeated).isEqualTo(firstResponse)
        assertThat(firstResponse).doesNotContain(one.toString(), missingReport.toString(), "PRIVATE")

        val json = com.fasterxml.jackson.module.kotlin.jacksonObjectMapper().readTree(firstResponse)
        assertThat(json["completedSessions"].asInt()).isEqualTo(3)
        assertThat(json["averagePercent"].asDouble()).isEqualTo(60.0)
        assertThat(json["medianPercent"].asDouble()).isEqualTo(60.0)
        assertThat(json["scoreDistribution"].map { it["count"].asInt() }).containsExactly(1, 0, 1, 0, 1)
        assertThat(json["incidentTypes"].map { it["count"].asInt() }).containsExactly(2, 1)
        assertThat(json["topErrors"][0]["criterionCode"].asText()).isEqualTo("ADDRESS")
        assertThat(json["topErrors"][0]["count"].asInt()).isEqualTo(2)
        assertThat(json["topErrors"][1]["criterionCode"].asText()).isEqualTo("SERVICES")
        assertThat(json["daily"].map { it["count"].asInt() }).containsExactly(2, 1)
        assertThat(json["daily"][0]["averagePercent"].asDouble()).isEqualTo(40.0)
        assertThat(json["daily"][1]["averagePercent"].asDouble()).isEqualTo(100.0)
    }

    private fun saveSession(scenario: ru.sirena112.core.domain.Scenario, state: SessionState, ended: Instant): UUID {
        val id = UUID.randomUUID()
        sessions.save(TrainingSession.restore(
            id = id, scenario = scenario, mode = SessionMode.CARD, state = state,
            operatorCard = OperatorCard(), cardRevision = 0,
            createdAt = ended.minusSeconds(600), startedAt = ended.minusSeconds(300), endedAt = ended,
            updatedAt = ended, failureReason = null, timeLimitEventEmitted = false
        ))
        return id
    }

    private fun report(sessionId: UUID, score: Double, vararg failed: String): SessionReport = SessionReport(
        sessionId = sessionId, score = score, maxScore = 100.0, passed = failed.isEmpty(),
        criteria = listOf("ADDRESS", "SERVICES").map { code ->
            CriterionScore(code, code !in failed, if (code in failed) 0.0 else 50.0, 50.0, "rubric")
        },
        errors = failed.map { ScoreError("CRITERION_$it", "rubric") },
        recommendations = emptyList()
    )
}
