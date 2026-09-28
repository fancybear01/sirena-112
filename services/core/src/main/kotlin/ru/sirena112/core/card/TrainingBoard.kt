package ru.sirena112.core.card

import org.springframework.web.bind.annotation.GetMapping
import org.springframework.web.bind.annotation.RequestMapping
import org.springframework.web.bind.annotation.RestController
import ru.sirena112.core.auth.Role
import ru.sirena112.core.auth.SessionAccess
import ru.sirena112.core.domain.SessionMode
import ru.sirena112.core.domain.SessionState
import ru.sirena112.core.domain.TrainingSession
import ru.sirena112.core.domain.TrainingSessionRepository
import java.time.Instant

data class TrainingBoardSession(
    val scenarioTitle: String,
    val mode: SessionMode,
    val state: SessionState,
    val startedAt: Instant?,
    val updatedAt: Instant
)

data class TrainingBoardSnapshot(
    val generatedAt: Instant,
    val activeSessions: List<TrainingBoardSession>,
    val analytics: TrainingAnalyticsSummary
)

/**
 * Read-only projection for a classroom display. It deliberately has no session,
 * account, card, address, phone, transcript or individual-score fields.
 */
@RestController
@RequestMapping("/api/teacher/board")
class TrainingBoardController(
    private val sessions: TrainingSessionRepository,
    private val analytics: TrainingAnalyticsService,
    private val access: SessionAccess
) {
    @GetMapping
    fun snapshot(): TrainingBoardSnapshot {
        val actor = access.current()
        val activeSessions = sessions.findAll().asSequence()
            .filter { session ->
                actor == null || actor.role == Role.ADMIN ||
                    (actor.role == Role.TEACHER && actor.groupId != null && session.groupId == actor.groupId)
            }
            .filter { it.state in ACTIVE_STATES }
            .sortedWith(compareByDescending<TrainingSession> { it.updatedAt }.thenBy { it.scenario.title })
            .map { session ->
                TrainingBoardSession(
                    scenarioTitle = session.scenario.title,
                    mode = session.mode,
                    state = session.state,
                    startedAt = session.startedAt,
                    updatedAt = session.updatedAt
                )
            }
            .toList()

        return TrainingBoardSnapshot(
            generatedAt = Instant.now(),
            activeSessions = activeSessions,
            analytics = analytics.summary()
        )
    }

    private companion object {
        val ACTIVE_STATES = setOf(
            SessionState.CREATED,
            SessionState.READY,
            SessionState.RINGING,
            SessionState.ACTIVE,
            SessionState.SCORING
        )
    }
}
