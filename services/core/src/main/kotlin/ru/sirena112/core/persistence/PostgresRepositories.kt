package ru.sirena112.core.persistence

import com.fasterxml.jackson.core.type.TypeReference
import com.fasterxml.jackson.databind.ObjectMapper
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty
import org.springframework.context.annotation.Bean
import org.springframework.context.annotation.Configuration
import org.springframework.dao.DuplicateKeyException
import org.springframework.jdbc.core.JdbcTemplate
import org.springframework.jdbc.core.RowMapper
import ru.sirena112.core.card.SessionReport
import ru.sirena112.core.card.SessionReportRepository
import ru.sirena112.core.classifier.CardScenarioFixtures
import ru.sirena112.core.classifier.ClassifierCatalog
import ru.sirena112.core.dispatch.ServiceAssignment
import ru.sirena112.core.dispatch.ServiceAssignmentRepository
import ru.sirena112.core.domain.*
import java.sql.ResultSet
import java.sql.Timestamp
import java.time.Instant
import java.util.UUID
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.CopyOnWriteArrayList

private fun ObjectMapper.json(value: Any): String = writeValueAsString(value)
private fun <T> ObjectMapper.value(json: String, type: Class<T>): T = readValue(json, type)
private fun Instant?.sqlTimestamp(): Timestamp? = this?.let(Timestamp::from)

class PostgresScenarioRepository(private val jdbc: JdbcTemplate, private val mapper: ObjectMapper) : ScenarioRepository {
    override fun save(scenario: Scenario): Scenario {
        jdbc.update("""
            INSERT INTO scenarios(id, body) VALUES (?, CAST(? AS jsonb))
            ON CONFLICT (id) DO UPDATE SET body = EXCLUDED.body, updated_at = now()
        """.trimIndent(), scenario.id, mapper.json(scenario))
        return scenario
    }

    override fun insertAllNew(scenarios: List<Scenario>) {
        scenarios.forEach { scenario ->
            jdbc.update("INSERT INTO scenarios(id, body) VALUES (?, CAST(? AS jsonb))", scenario.id, mapper.json(scenario))
        }
    }

    override fun findById(id: UUID): Scenario? = jdbc.query(
        "SELECT body::text FROM scenarios WHERE id = ?", { rs, _ -> mapper.value(rs.getString(1), Scenario::class.java) }, id
    ).firstOrNull()

    override fun findAll(): List<Scenario> = jdbc.query("SELECT body::text FROM scenarios ORDER BY id") { rs, _ ->
        mapper.value(rs.getString(1), Scenario::class.java)
    }
}

class PostgresTrainingSessionRepository(private val jdbc: JdbcTemplate, private val mapper: ObjectMapper) : TrainingSessionRepository {
    override fun save(session: TrainingSession): TrainingSession {
        jdbc.update("""
            INSERT INTO training_sessions(id, scenario_id, scenario_body, mode, state, card_body, card_revision, created_at, started_at, ended_at, updated_at, failure_reason, time_limit_event_emitted, student_id, teacher_id, group_id)
            VALUES (?, ?, CAST(? AS jsonb), ?, ?, CAST(? AS jsonb), ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (id) DO UPDATE SET scenario_body = EXCLUDED.scenario_body, mode = EXCLUDED.mode,
              state = EXCLUDED.state, card_body = EXCLUDED.card_body, card_revision = EXCLUDED.card_revision,
              started_at = EXCLUDED.started_at, ended_at = EXCLUDED.ended_at, updated_at = EXCLUDED.updated_at,
              failure_reason = EXCLUDED.failure_reason, time_limit_event_emitted = EXCLUDED.time_limit_event_emitted,
              student_id = EXCLUDED.student_id, teacher_id = EXCLUDED.teacher_id, group_id = EXCLUDED.group_id
        """.trimIndent(), session.id, session.scenario.id, mapper.json(session.scenario), session.mode.name, session.state.name,
            mapper.json(session.operatorCard), session.cardRevision, session.createdAt.sqlTimestamp(), session.startedAt.sqlTimestamp(), session.endedAt.sqlTimestamp(),
            session.updatedAt.sqlTimestamp(), session.failureReason, session.timeLimitEventEmitted,
            session.studentId, session.teacherId, session.groupId)
        return session
    }

    override fun findById(id: UUID): TrainingSession? = jdbc.query(
        "SELECT * FROM training_sessions WHERE id = ?", sessionMapper, id
    ).firstOrNull()

    override fun findAll(): List<TrainingSession> = jdbc.query("SELECT * FROM training_sessions ORDER BY created_at", sessionMapper)

    private val sessionMapper = RowMapper { rs: ResultSet, _: Int ->
        TrainingSession.restore(
            id = rs.getObject("id", UUID::class.java),
            scenario = mapper.value(rs.getString("scenario_body"), Scenario::class.java),
            mode = SessionMode.valueOf(rs.getString("mode")),
            state = SessionState.valueOf(rs.getString("state")),
            operatorCard = mapper.value(rs.getString("card_body"), OperatorCard::class.java),
            cardRevision = rs.getInt("card_revision"),
            createdAt = rs.getTimestamp("created_at").toInstant(),
            startedAt = rs.getTimestamp("started_at")?.toInstant(),
            endedAt = rs.getTimestamp("ended_at")?.toInstant(),
            updatedAt = rs.getTimestamp("updated_at").toInstant(),
            failureReason = rs.getString("failure_reason"),
            timeLimitEventEmitted = rs.getBoolean("time_limit_event_emitted"),
            studentId = rs.getObject("student_id", UUID::class.java),
            teacherId = rs.getObject("teacher_id", UUID::class.java),
            groupId = rs.getObject("group_id", UUID::class.java)
        )
    }
}

class PostgresSessionEventRepository(private val jdbc: JdbcTemplate, private val mapper: ObjectMapper) : SessionEventRepository, SessionEventSubscription {
    private val listeners = ConcurrentHashMap<UUID, CopyOnWriteArrayList<(SessionEvent) -> Unit>>()
    private val payloadType = object : TypeReference<Map<String, Any?>>() {}

    override fun saveIfAbsent(event: SessionEvent): Boolean = try {
        val inserted = jdbc.update(
            "INSERT INTO session_events(event_id, session_id, type, occurred_at, source, payload) VALUES (?, ?, ?, ?, ?, CAST(? AS jsonb))",
            event.eventId, event.sessionId, event.type, event.timestamp.sqlTimestamp(), event.source, mapper.json(event.payload)
        ) == 1
        if (inserted) listeners[event.sessionId]?.forEach { runCatching { it(event) } }
        inserted
    } catch (_: DuplicateKeyException) {
        false
    }

    override fun findById(eventId: UUID): SessionEvent? = jdbc.query(
        "SELECT * FROM session_events WHERE event_id = ?", eventMapper, eventId
    ).firstOrNull()

    override fun findBySessionId(sessionId: UUID): List<SessionEvent> = jdbc.query(
        "SELECT * FROM session_events WHERE session_id = ? ORDER BY occurred_at, event_id", eventMapper, sessionId
    )

    override fun subscribe(sessionId: UUID, listener: (SessionEvent) -> Unit): () -> Unit {
        val current = listeners.computeIfAbsent(sessionId) { CopyOnWriteArrayList() }
        current += listener
        return { current.remove(listener); if (current.isEmpty()) listeners.remove(sessionId, current) }
    }

    private val eventMapper = RowMapper { rs: ResultSet, _: Int -> SessionEvent(
        eventId = rs.getObject("event_id", UUID::class.java), sessionId = rs.getObject("session_id", UUID::class.java),
        type = rs.getString("type"), timestamp = rs.getTimestamp("occurred_at").toInstant(), source = rs.getString("source"),
        payload = mapper.readValue(rs.getString("payload"), payloadType)
    ) }
}

class PostgresSessionReportRepository(private val jdbc: JdbcTemplate, private val mapper: ObjectMapper) : SessionReportRepository {
    override fun save(report: SessionReport): SessionReport {
        jdbc.update("""INSERT INTO session_reports(session_id, body) VALUES (?, CAST(? AS jsonb))
            ON CONFLICT (session_id) DO UPDATE SET body = EXCLUDED.body, updated_at = now()""", report.sessionId, mapper.json(report))
        return report
    }
    override fun findBySessionIdOrNull(sessionId: UUID): SessionReport? = jdbc.query(
        "SELECT body::text FROM session_reports WHERE session_id = ?", { rs, _ -> mapper.value(rs.getString(1), SessionReport::class.java) }, sessionId
    ).firstOrNull()
    override fun findAll(): List<SessionReport> = jdbc.query(
        "SELECT body::text FROM session_reports ORDER BY session_id"
    ) { rs, _ -> mapper.value(rs.getString(1), SessionReport::class.java) }
}

class PostgresServiceAssignmentRepository(private val jdbc: JdbcTemplate, private val mapper: ObjectMapper) : ServiceAssignmentRepository {
    override fun save(assignment: ServiceAssignment): ServiceAssignment {
        jdbc.update("""INSERT INTO service_assignments(id, session_id, body) VALUES (?, ?, CAST(? AS jsonb))
            ON CONFLICT (id) DO UPDATE SET body = EXCLUDED.body, updated_at = now()""", assignment.id, assignment.sessionId, mapper.json(assignment))
        return assignment
    }
    override fun findById(id: UUID): ServiceAssignment? = jdbc.query(
        "SELECT body::text FROM service_assignments WHERE id = ?", { rs, _ -> mapper.value(rs.getString(1), ServiceAssignment::class.java) }, id
    ).firstOrNull()
    override fun findBySessionId(sessionId: UUID): List<ServiceAssignment> = jdbc.query(
        "SELECT body::text FROM service_assignments WHERE session_id = ? ORDER BY id", { rs, _ -> mapper.value(rs.getString(1), ServiceAssignment::class.java) }, sessionId
    )
    override fun existsBySessionId(sessionId: UUID): Boolean = jdbc.queryForObject(
        "SELECT EXISTS(SELECT 1 FROM service_assignments WHERE session_id = ?)", Boolean::class.java, sessionId
    )
}

@Configuration
@ConditionalOnProperty(name = ["core.storage"], havingValue = "postgres")
class PostgresPersistenceConfiguration {
    @Bean fun scenarioRepository(jdbc: JdbcTemplate, mapper: ObjectMapper, catalog: ClassifierCatalog, fixtures: CardScenarioFixtures): ScenarioRepository =
        PostgresScenarioRepository(jdbc, mapper).also { repository -> fixtures.loadAll(catalog.contractsDir().resolve("examples")).forEach(repository::save) }
    @Bean fun trainingSessionRepository(jdbc: JdbcTemplate, mapper: ObjectMapper): TrainingSessionRepository = PostgresTrainingSessionRepository(jdbc, mapper)
    @Bean fun sessionEventRepository(jdbc: JdbcTemplate, mapper: ObjectMapper): PostgresSessionEventRepository = PostgresSessionEventRepository(jdbc, mapper)
    @Bean fun sessionReportRepository(jdbc: JdbcTemplate, mapper: ObjectMapper): SessionReportRepository = PostgresSessionReportRepository(jdbc, mapper)
    @Bean fun serviceAssignmentRepository(jdbc: JdbcTemplate, mapper: ObjectMapper): ServiceAssignmentRepository = PostgresServiceAssignmentRepository(jdbc, mapper)
}
