package ru.sirena112.core.card

import com.fasterxml.jackson.databind.ObjectMapper
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty
import org.springframework.context.annotation.Bean
import org.springframework.context.annotation.Configuration
import org.springframework.jdbc.core.JdbcTemplate
import ru.sirena112.core.domain.Scenario
import java.sql.ResultSet
import java.util.UUID
import java.util.concurrent.ConcurrentHashMap

enum class ScenarioStatus { DRAFT, APPROVED }
enum class ScenarioSource { MANUAL, AI, COPY }
data class ScenarioWorkflow(
    val id: UUID,
    val familyId: UUID,
    val version: Int,
    val revision: Int,
    val status: ScenarioStatus,
    val scenario: Scenario,
    val comment: String,
    val ownerId: UUID?,
    val groupId: UUID?,
    val source: ScenarioSource
)

interface ScenarioWorkflowRepository {
    fun insert(item: ScenarioWorkflow)
    /** Compare-and-set prevents concurrent edits and approval of a stale draft. */
    fun updateDraft(item: ScenarioWorkflow, expectedRevision: Int): Boolean
    fun findById(id: UUID): ScenarioWorkflow?
    fun findAll(): List<ScenarioWorkflow>
}

class InMemoryScenarioWorkflowRepository : ScenarioWorkflowRepository {
    private val data = ConcurrentHashMap<UUID, ScenarioWorkflow>()
    @Synchronized override fun insert(item: ScenarioWorkflow) {
        require(data.values.none { it.familyId == item.familyId && it.version == item.version }) { "Версия уже существует" }
        check(data.putIfAbsent(item.id, item) == null) { "Сценарий уже существует" }
    }
    @Synchronized override fun updateDraft(item: ScenarioWorkflow, expectedRevision: Int): Boolean {
        val old = data[item.id] ?: return false
        if (old.status != ScenarioStatus.DRAFT || old.revision != expectedRevision) return false
        data[item.id] = item
        return true
    }
    override fun findById(id: UUID): ScenarioWorkflow? = data[id]
    override fun findAll(): List<ScenarioWorkflow> = data.values.sortedWith(compareBy({ it.familyId }, { it.version }))
}

class PostgresScenarioWorkflowRepository(private val jdbc: JdbcTemplate, private val mapper: ObjectMapper) : ScenarioWorkflowRepository {
    override fun insert(item: ScenarioWorkflow) {
        jdbc.update("""INSERT INTO scenario_workflow(id, family_id, version, revision, status, body, comment, owner_id, group_id, source)
            VALUES (?, ?, ?, ?, ?, CAST(? AS jsonb), ?, ?, ?, ?)""", item.id, item.familyId, item.version,
            item.revision, item.status.name, mapper.writeValueAsString(item.scenario), item.comment,
            item.ownerId, item.groupId, item.source.name)
    }
    override fun updateDraft(item: ScenarioWorkflow, expectedRevision: Int): Boolean = jdbc.update(
        """UPDATE scenario_workflow SET revision=?, status=?, body=CAST(? AS jsonb), comment=?, updated_at=now()
            WHERE id=? AND status='DRAFT' AND revision=?""", item.revision, item.status.name,
        mapper.writeValueAsString(item.scenario), item.comment, item.id, expectedRevision) == 1
    override fun findById(id: UUID): ScenarioWorkflow? = jdbc.query("SELECT * FROM scenario_workflow WHERE id=?", rowMapper, id).firstOrNull()
    override fun findAll(): List<ScenarioWorkflow> = jdbc.query("SELECT * FROM scenario_workflow ORDER BY family_id, version", rowMapper)
    private val rowMapper = { rs: ResultSet, _: Int -> ScenarioWorkflow(
        rs.getObject("id", UUID::class.java), rs.getObject("family_id", UUID::class.java), rs.getInt("version"),
        rs.getInt("revision"), ScenarioStatus.valueOf(rs.getString("status")),
        mapper.readValue(rs.getString("body"), Scenario::class.java), rs.getString("comment"),
        rs.getObject("owner_id", UUID::class.java), rs.getObject("group_id", UUID::class.java),
        ScenarioSource.valueOf(rs.getString("source"))
    ) }
}

@Configuration
class ScenarioWorkflowPersistence {
    @Bean
    @ConditionalOnProperty(name = ["core.storage"], havingValue = "in-memory", matchIfMissing = true)
    fun inMemoryScenarioWorkflowRepository(): ScenarioWorkflowRepository = InMemoryScenarioWorkflowRepository()

    @Bean
    @ConditionalOnProperty(name = ["core.storage"], havingValue = "postgres")
    fun postgresScenarioWorkflowRepository(jdbc: JdbcTemplate, mapper: ObjectMapper): ScenarioWorkflowRepository =
        PostgresScenarioWorkflowRepository(jdbc, mapper)
}
