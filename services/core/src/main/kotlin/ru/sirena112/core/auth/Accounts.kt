package ru.sirena112.core.auth

import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty
import org.springframework.context.annotation.Bean
import org.springframework.context.annotation.Configuration
import org.springframework.jdbc.core.JdbcTemplate
import java.sql.ResultSet
import java.util.UUID
import java.util.concurrent.ConcurrentHashMap

enum class Role { ADMIN, TEACHER, STUDENT }

data class TrainingGroup(val id: UUID, val name: String)
data class AuthAccount(
    val id: UUID,
    val username: String,
    val passwordHash: String,
    val role: Role,
    val displayName: String,
    val groupId: UUID? = null,
    val locked: Boolean = false,
    val enabled: Boolean = true
)

interface AccountRepository {
    fun insert(account: AuthAccount)
    fun update(account: AuthAccount)
    fun findById(id: UUID): AuthAccount?
    fun findByUsername(username: String): AuthAccount?
    fun findAll(): List<AuthAccount>
}

interface GroupRepository {
    fun insert(group: TrainingGroup)
    fun findById(id: UUID): TrainingGroup?
    fun findAll(): List<TrainingGroup>
}

data class AuthAudit(val actorId: UUID?, val action: String, val subjectId: UUID?, val outcome: String, val requestId: String?)
interface AuthAuditRepository { fun append(entry: AuthAudit) }

class InMemoryAccountRepository : AccountRepository {
    private val accounts = ConcurrentHashMap<UUID, AuthAccount>()
    @Synchronized override fun insert(account: AuthAccount) {
        if (accounts.containsKey(account.id) || accounts.values.any { it.username == account.username }) {
            throw IllegalStateException("Учётная запись уже существует")
        }
        accounts[account.id] = account
    }
    override fun update(account: AuthAccount) { accounts[account.id] = account }
    override fun findById(id: UUID): AuthAccount? = accounts[id]
    override fun findByUsername(username: String): AuthAccount? = accounts.values.firstOrNull { it.username == username }
    override fun findAll(): List<AuthAccount> = accounts.values.sortedBy { it.username }
}

class InMemoryGroupRepository : GroupRepository {
    private val groups = ConcurrentHashMap<UUID, TrainingGroup>()
    @Synchronized override fun insert(group: TrainingGroup) {
        if (groups.containsKey(group.id) || groups.values.any { it.name == group.name }) {
            throw IllegalStateException("Группа уже существует")
        }
        groups[group.id] = group
    }
    override fun findById(id: UUID): TrainingGroup? = groups[id]
    override fun findAll(): List<TrainingGroup> = groups.values.sortedBy { it.name }
}

class InMemoryAuthAuditRepository : AuthAuditRepository {
    val entries = mutableListOf<AuthAudit>()
    @Synchronized override fun append(entry: AuthAudit) { entries += entry }
}

class PostgresAccountRepository(private val jdbc: JdbcTemplate) : AccountRepository {
    override fun insert(account: AuthAccount) {
        jdbc.update("""INSERT INTO auth_accounts(id, username, password_hash, role, display_name, group_id, locked, enabled)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)""", account.id, account.username, account.passwordHash, account.role.name,
            account.displayName, account.groupId, account.locked, account.enabled)
    }
    override fun update(account: AuthAccount) {
        check(jdbc.update("""UPDATE auth_accounts SET password_hash=?, role=?, display_name=?, group_id=?, locked=?, enabled=? WHERE id=?""",
            account.passwordHash, account.role.name, account.displayName, account.groupId, account.locked, account.enabled, account.id) == 1)
    }
    override fun findById(id: UUID): AuthAccount? = jdbc.query("SELECT * FROM auth_accounts WHERE id=?", mapper, id).firstOrNull()
    override fun findByUsername(username: String): AuthAccount? = jdbc.query("SELECT * FROM auth_accounts WHERE username=?", mapper, username).firstOrNull()
    override fun findAll(): List<AuthAccount> = jdbc.query("SELECT * FROM auth_accounts ORDER BY username", mapper)
    private val mapper = { rs: ResultSet, _: Int -> AuthAccount(
        rs.getObject("id", UUID::class.java), rs.getString("username"), rs.getString("password_hash"),
        Role.valueOf(rs.getString("role")), rs.getString("display_name"), rs.getObject("group_id", UUID::class.java),
        rs.getBoolean("locked"), rs.getBoolean("enabled")
    ) }
}

class PostgresGroupRepository(private val jdbc: JdbcTemplate) : GroupRepository {
    override fun insert(group: TrainingGroup) { jdbc.update("INSERT INTO training_groups(id, name) VALUES (?, ?)", group.id, group.name) }
    override fun findById(id: UUID): TrainingGroup? = jdbc.query("SELECT id, name FROM training_groups WHERE id=?",
        { rs, _ -> TrainingGroup(rs.getObject("id", UUID::class.java), rs.getString("name")) }, id).firstOrNull()
    override fun findAll(): List<TrainingGroup> = jdbc.query("SELECT id, name FROM training_groups ORDER BY name") { rs, _ ->
        TrainingGroup(rs.getObject("id", UUID::class.java), rs.getString("name"))
    }
}

class PostgresAuthAuditRepository(private val jdbc: JdbcTemplate) : AuthAuditRepository {
    override fun append(entry: AuthAudit) {
        jdbc.update("INSERT INTO auth_audit(id, actor_id, action, subject_id, outcome, request_id) VALUES (?, ?, ?, ?, ?, ?)",
            UUID.randomUUID(), entry.actorId, entry.action, entry.subjectId, entry.outcome, entry.requestId)
    }
}

@Configuration
class AuthPersistenceConfiguration {
    @Bean
    @ConditionalOnProperty(name = ["core.storage"], havingValue = "in-memory", matchIfMissing = true)
    fun inMemoryAccountRepository(): AccountRepository = InMemoryAccountRepository()
    @Bean
    @ConditionalOnProperty(name = ["core.storage"], havingValue = "in-memory", matchIfMissing = true)
    fun inMemoryGroupRepository(): GroupRepository = InMemoryGroupRepository()
    @Bean
    @ConditionalOnProperty(name = ["core.storage"], havingValue = "in-memory", matchIfMissing = true)
    fun inMemoryAuthAuditRepository(): AuthAuditRepository = InMemoryAuthAuditRepository()
    @Bean
    @ConditionalOnProperty(name = ["core.storage"], havingValue = "postgres")
    fun postgresAccountRepository(jdbc: JdbcTemplate): AccountRepository = PostgresAccountRepository(jdbc)
    @Bean
    @ConditionalOnProperty(name = ["core.storage"], havingValue = "postgres")
    fun postgresGroupRepository(jdbc: JdbcTemplate): GroupRepository = PostgresGroupRepository(jdbc)
    @Bean
    @ConditionalOnProperty(name = ["core.storage"], havingValue = "postgres")
    fun postgresAuthAuditRepository(jdbc: JdbcTemplate): AuthAuditRepository = PostgresAuthAuditRepository(jdbc)
}
