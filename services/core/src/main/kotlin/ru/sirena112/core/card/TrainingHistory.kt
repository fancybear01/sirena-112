package ru.sirena112.core.card

import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty
import org.springframework.context.annotation.Bean
import org.springframework.context.annotation.Configuration
import org.springframework.http.HttpStatus
import org.springframework.jdbc.core.JdbcTemplate
import org.springframework.stereotype.Service
import org.springframework.transaction.annotation.Transactional
import org.springframework.web.bind.annotation.GetMapping
import org.springframework.web.bind.annotation.PathVariable
import org.springframework.web.bind.annotation.PostMapping
import org.springframework.web.bind.annotation.RequestBody
import org.springframework.web.bind.annotation.RequestMapping
import org.springframework.web.bind.annotation.ResponseStatus
import org.springframework.web.bind.annotation.RestController
import org.springframework.web.server.ResponseStatusException
import ru.sirena112.core.auth.AccountRepository
import ru.sirena112.core.auth.AuthAudit
import ru.sirena112.core.auth.AuthAuditRepository
import ru.sirena112.core.auth.Role
import ru.sirena112.core.auth.SessionAccess
import ru.sirena112.core.domain.SessionState
import ru.sirena112.core.domain.SessionEventRepository
import ru.sirena112.core.domain.SessionEventType
import ru.sirena112.core.domain.TrainingSession
import ru.sirena112.core.domain.TrainingSessionRepository
import java.time.Duration
import java.time.Instant
import java.util.UUID
import java.util.concurrent.CopyOnWriteArrayList

enum class FeedbackKind { COMMENT, CORRECTION }

data class TrainingFeedback(
    val id: UUID,
    val sessionId: UUID,
    val authorId: UUID,
    val kind: FeedbackKind,
    val text: String,
    val createdAt: Instant,
    val oldScore: Double? = null,
    val newScore: Double? = null
)

interface TrainingFeedbackRepository {
    fun append(item: TrainingFeedback)
    fun findBySessionId(sessionId: UUID): List<TrainingFeedback>
}

class InMemoryTrainingFeedbackRepository : TrainingFeedbackRepository {
    private val items = CopyOnWriteArrayList<TrainingFeedback>()
    override fun append(item: TrainingFeedback) { items += item }
    override fun findBySessionId(sessionId: UUID): List<TrainingFeedback> = items.filter { it.sessionId == sessionId }
        .sortedWith(compareBy({ it.createdAt }, { it.id }))
}

class PostgresTrainingFeedbackRepository(private val jdbc: JdbcTemplate) : TrainingFeedbackRepository {
    override fun append(item: TrainingFeedback) {
        jdbc.update("""INSERT INTO training_feedback(id, session_id, author_id, kind, text, created_at, old_score, new_score)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)""", item.id, item.sessionId, item.authorId,
            item.kind.name, item.text, java.sql.Timestamp.from(item.createdAt), item.oldScore, item.newScore)
    }
    override fun findBySessionId(sessionId: UUID): List<TrainingFeedback> = jdbc.query(
        "SELECT * FROM training_feedback WHERE session_id=? ORDER BY created_at, id", { rs, _ -> TrainingFeedback(
            rs.getObject("id", UUID::class.java), rs.getObject("session_id", UUID::class.java),
            rs.getObject("author_id", UUID::class.java), FeedbackKind.valueOf(rs.getString("kind")),
            rs.getString("text"), rs.getTimestamp("created_at").toInstant(),
            rs.getDouble("old_score").takeUnless { rs.wasNull() },
            rs.getDouble("new_score").takeUnless { rs.wasNull() }
        ) }, sessionId)
}

@Configuration
class TrainingFeedbackPersistence {
    @Bean @ConditionalOnProperty(name = ["core.storage"], havingValue = "in-memory", matchIfMissing = true)
    fun inMemoryTrainingFeedbackRepository(): TrainingFeedbackRepository = InMemoryTrainingFeedbackRepository()

    @Bean @ConditionalOnProperty(name = ["core.storage"], havingValue = "postgres")
    fun postgresTrainingFeedbackRepository(jdbc: JdbcTemplate): TrainingFeedbackRepository = PostgresTrainingFeedbackRepository(jdbc)
}

data class TrainingHistoryItem(
    val sessionId: UUID,
    val studentId: UUID?,
    val studentName: String?,
    val scenarioId: UUID,
    val scenarioTitle: String,
    val scenarioProfile: String,
    val scenarioVersion: Int,
    val state: SessionState,
    val createdAt: Instant,
    val startedAt: Instant?,
    val endedAt: Instant?,
    val elapsedSeconds: Long?,
    val timeLimitSeconds: Int,
    val exceededLimit: Boolean?,
    val comparison: AttemptComparison?,
    val originalReport: SessionReport?,
    val effectiveScore: Double?,
    val feedback: List<TrainingFeedback>
)

data class AttemptComparison(
    val expectedClassifierCode: String,
    val actualClassifierCode: String?,
    val classifierMatches: Boolean,
    val expectedServiceIds: Set<String>,
    val actualServiceIds: Set<String>,
    val servicesMatch: Boolean,
    val expectedAnswers: Map<String, List<String>>,
    val actualAnswers: Map<String, List<String>>,
    val answersMatch: Boolean,
    val finalTranscript: List<String>
)

data class TrainingHistorySummary(val assigned: Int, val completed: Int, val averagePercent: Double?)
data class TrainingHistory(val summary: TrainingHistorySummary, val attempts: List<TrainingHistoryItem>)
data class CommentRequest(val text: String)
data class CorrectionRequest(val newScore: Double, val reason: String)

@Service
class TrainingHistoryService(
    private val sessions: TrainingSessionRepository,
    private val reports: SessionReportRepository,
    private val events: SessionEventRepository,
    private val feedback: TrainingFeedbackRepository,
    private val accounts: AccountRepository,
    private val access: SessionAccess,
    private val audit: AuthAuditRepository
) {
    fun teacherHistory(): TrainingHistory {
        val actor = access.current()
        val visible = sessions.findAll().filter { session -> actor == null || when (actor.role) {
            Role.ADMIN -> true
            Role.TEACHER -> actor.groupId != null && session.groupId == actor.groupId
            Role.STUDENT -> false
        } }
        return history(visible)
    }

    fun studentHistory(): TrainingHistory {
        val actor = access.current()
        return history(sessions.findAll().filter { actor == null || it.studentId == actor.id })
    }

    fun teacherAttempt(sessionId: UUID): TrainingHistoryItem {
        access.teacherCanRead(sessionId)
        return item(sessionId)
    }

    fun studentAttempt(sessionId: UUID): TrainingHistoryItem {
        access.studentOwns(sessionId)
        return item(sessionId)
    }

    @Transactional
    fun comment(sessionId: UUID, request: CommentRequest): TrainingHistoryItem {
        access.teacherCanWrite(sessionId)
        val actor = access.current() ?: throw ResponseStatusException(HttpStatus.FORBIDDEN, "Требуется преподаватель")
        val text = request.text.trim()
        require(text.length in 1..2000) { "Комментарий должен содержать 1–2000 символов" }
        feedback.append(TrainingFeedback(UUID.randomUUID(), sessionId, actor.id, FeedbackKind.COMMENT, text, Instant.now()))
        audit.append(AuthAudit(actor.id, "TRAINING_COMMENT", sessionId, "OK", null))
        return item(sessionId)
    }

    @Transactional
    fun correct(sessionId: UUID, request: CorrectionRequest): TrainingHistoryItem {
        access.teacherCanWrite(sessionId)
        val actor = access.current() ?: throw ResponseStatusException(HttpStatus.FORBIDDEN, "Требуется преподаватель")
        val report = reports.findBySessionIdOrNull(sessionId)
            ?: throw ResponseStatusException(HttpStatus.CONFLICT, "Исходная оценка ещё не сформирована")
        val reason = request.reason.trim()
        require(reason.length in 5..2000) { "Причина должна содержать 5–2000 символов" }
        require(request.newScore.isFinite() && request.newScore in 0.0..report.maxScore) { "Оценка вне допустимого диапазона" }
        val previous = feedback.findBySessionId(sessionId).lastOrNull { it.kind == FeedbackKind.CORRECTION }?.newScore ?: report.score
        require(previous != request.newScore) { "Новая оценка совпадает с текущей" }
        feedback.append(TrainingFeedback(UUID.randomUUID(), sessionId, actor.id, FeedbackKind.CORRECTION, reason,
            Instant.now(), previous, request.newScore))
        audit.append(AuthAudit(actor.id, "TRAINING_SCORE_CORRECTED", sessionId, "OK", null))
        return item(sessionId)
    }

    private fun item(sessionId: UUID): TrainingHistoryItem = sessions.findById(sessionId)?.let(::item)
        ?: throw ResponseStatusException(HttpStatus.NOT_FOUND, "Занятие не найдено")

    private fun history(visible: List<TrainingSession>): TrainingHistory {
        val items = visible.sortedWith(compareByDescending<TrainingSession> { it.createdAt }.thenByDescending { it.id })
            .map(::item)
        val completed = items.filter { it.originalReport != null }
        val percentages = completed.mapNotNull { attempt -> attempt.originalReport?.maxScore?.takeIf { it > 0 }
            ?.let { attempt.effectiveScore!! / it * 100.0 } }
        return TrainingHistory(TrainingHistorySummary(items.size, completed.size,
            percentages.takeIf { it.isNotEmpty() }?.average()), items)
    }

    private fun item(session: TrainingSession): TrainingHistoryItem {
        val report = reports.findBySessionIdOrNull(session.id)
        val notes = feedback.findBySessionId(session.id)
        val elapsed = session.startedAt?.let { start -> session.endedAt?.let { Duration.between(start, it).seconds.coerceAtLeast(0) } }
        val truth = session.scenario.groundTruth
        val calculation = session.operatorCard.calculation
        val answers = session.operatorCard.input.incident?.answers?.associate { it.questionId to it.optionIds } ?: emptyMap()
        val services = calculation?.services?.map { it.id }?.toSet() ?: emptySet()
        val comparison = AttemptComparison(truth.classifierCode, calculation?.classifierCode,
            truth.matchesCalculation(calculation), truth.expectedServiceIds(), services,
            truth.expectedServiceIds() == services, truth.expectedAnswers(), answers,
            truth.expectedAnswers() == answers,
            events.findBySessionId(session.id).filter { it.type == SessionEventType.TRANSCRIPT_FINAL.value }
                .mapNotNull { it.payload["text"] as? String }.filter { it.isNotBlank() })
        return TrainingHistoryItem(session.id, session.studentId,
            session.studentId?.let { accounts.findById(it)?.displayName }, session.scenario.id,
            session.scenario.title, session.scenario.profile, session.scenario.version, session.state, session.createdAt,
            session.startedAt, session.endedAt, elapsed, session.scenario.timeLimitSeconds,
            elapsed?.let { it > session.scenario.timeLimitSeconds }, comparison.takeIf { report != null }, report,
            notes.lastOrNull { it.kind == FeedbackKind.CORRECTION }?.newScore ?: report?.score, notes)
    }
}

@RestController
@RequestMapping("/api/teacher/history")
class TeacherHistoryController(private val service: TrainingHistoryService) {
    @GetMapping fun history(): TrainingHistory = service.teacherHistory()
    @GetMapping("/{sessionId}") fun attempt(@PathVariable sessionId: UUID): TrainingHistoryItem = service.teacherAttempt(sessionId)
    @PostMapping("/{sessionId}/comments") @ResponseStatus(HttpStatus.CREATED)
    fun comment(@PathVariable sessionId: UUID, @RequestBody body: CommentRequest): TrainingHistoryItem = service.comment(sessionId, body)
    @PostMapping("/{sessionId}/corrections") @ResponseStatus(HttpStatus.CREATED)
    fun correct(@PathVariable sessionId: UUID, @RequestBody body: CorrectionRequest): TrainingHistoryItem = service.correct(sessionId, body)
}

@RestController
@RequestMapping("/api/student/history")
class StudentHistoryController(private val service: TrainingHistoryService) {
    @GetMapping fun history(): TrainingHistory = service.studentHistory()
    @GetMapping("/{sessionId}") fun attempt(@PathVariable sessionId: UUID): TrainingHistoryItem = service.studentAttempt(sessionId)
}
