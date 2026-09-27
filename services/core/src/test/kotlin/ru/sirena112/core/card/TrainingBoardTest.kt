package ru.sirena112.core.card

import com.fasterxml.jackson.module.kotlin.jacksonObjectMapper
import org.assertj.core.api.Assertions.assertThat
import org.junit.jupiter.api.Test
import org.springframework.beans.factory.annotation.Autowired
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc
import org.springframework.boot.test.context.SpringBootTest
import org.springframework.test.annotation.DirtiesContext
import org.springframework.test.web.servlet.MockMvc
import org.springframework.test.web.servlet.get
import ru.sirena112.core.classifier.AddressInput
import ru.sirena112.core.classifier.CallerInput
import ru.sirena112.core.classifier.OperatorCardInput
import ru.sirena112.core.domain.OperatorCard
import ru.sirena112.core.domain.Scenario
import ru.sirena112.core.domain.ScenarioRepository
import ru.sirena112.core.domain.SessionMode
import ru.sirena112.core.domain.SessionState
import ru.sirena112.core.domain.TrainingSession
import ru.sirena112.core.domain.TrainingSessionRepository
import java.time.Instant
import java.util.UUID

@SpringBootTest
@AutoConfigureMockMvc
@DirtiesContext(classMode = DirtiesContext.ClassMode.BEFORE_CLASS)
class TrainingBoardTest {
    @Autowired lateinit var mvc: MockMvc
    @Autowired lateinit var scenarios: ScenarioRepository
    @Autowired lateinit var sessions: TrainingSessionRepository
    @Autowired lateinit var reports: SessionReportRepository

    @Test
    @DirtiesContext(methodMode = DirtiesContext.MethodMode.AFTER_METHOD)
    fun `board returns active stages and aggregates without personal session data`() {
        val scenario = scenarios.findAll().first()
        val activeCard = saveSession(scenario, SessionMode.CARD, SessionState.ACTIVE, "2026-09-28T09:00:00Z")
        val ringingCall = saveSession(scenario, SessionMode.VOICE, SessionState.RINGING, "2026-09-28T09:05:00Z")
        val scored = saveSession(scenario, SessionMode.CARD, SessionState.SCORED, "2026-09-28T08:00:00Z", ended = true)
        reports.save(SessionReport(
            sessionId = scored,
            score = 75.0,
            maxScore = 100.0,
            passed = false,
            criteria = listOf(CriterionScore("ADDRESS", false, 0.0, 25.0, "PRIVATE_TRANSCRIPT")),
            errors = listOf(ScoreError("CRITERION_ADDRESS", "PRIVATE_TRANSCRIPT")),
            recommendations = listOf("PRIVATE_RECOMMENDATION")
        ))

        val response = mvc.get("/api/teacher/board")
            .andExpect { status { isOk() } }
            .andReturn().response.contentAsString
        val json = jacksonObjectMapper().readTree(response)

        assertThat(json["activeSessions"]).hasSize(2)
        assertThat(json["activeSessions"].map { it["state"].asText() })
            .containsExactly(SessionState.RINGING.name, SessionState.ACTIVE.name)
        assertThat(json["activeSessions"].map { it["mode"].asText() })
            .containsExactly(SessionMode.VOICE.name, SessionMode.CARD.name)
        assertThat(json["analytics"]["completedSessions"].asInt()).isEqualTo(1)
        assertThat(json["analytics"]["averagePercent"].asDouble()).isEqualTo(75.0)
        assertThat(json["analytics"]["topErrors"][0]["criterionCode"].asText()).isEqualTo("ADDRESS")

        assertThat(response).doesNotContain(
            activeCard.toString(), ringingCall.toString(), scored.toString(),
            "PRIVATE_NAME", "PRIVATE_PHONE", "PRIVATE_ADDRESS", "PRIVATE_TRANSCRIPT", "PRIVATE_RECOMMENDATION"
        )
        assertThat(json["activeSessions"][0].fieldNames().asSequence().toList())
            .containsExactlyInAnyOrder("scenarioTitle", "mode", "state", "startedAt", "updatedAt")
    }

    private fun saveSession(
        scenario: Scenario,
        mode: SessionMode,
        state: SessionState,
        timestamp: String,
        ended: Boolean = false
    ): UUID {
        val at = Instant.parse(timestamp)
        val id = UUID.randomUUID()
        sessions.save(TrainingSession.restore(
            id = id,
            scenario = scenario,
            mode = mode,
            state = state,
            operatorCard = OperatorCard(OperatorCardInput(
                caller = CallerInput(
                    phoneNumbers = listOf(ru.sirena112.core.classifier.PhoneNumberInput("PRIVATE_PHONE", "AON")),
                    fullName = "PRIVATE_NAME"
                ),
                address = AddressInput("PRIVATE_ADDRESS"),
                description = "PRIVATE_TRANSCRIPT"
            )),
            cardRevision = 1,
            createdAt = at.minusSeconds(60),
            startedAt = at,
            endedAt = at.takeIf { ended },
            updatedAt = at,
            failureReason = null,
            timeLimitEventEmitted = false
        ))
        return id
    }
}
