package ru.sirena112.core.auth

import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty
import org.springframework.http.HttpStatus
import org.springframework.security.authentication.AuthenticationManager
import org.springframework.security.authentication.BadCredentialsException
import org.springframework.security.core.AuthenticationException
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken
import org.springframework.security.core.context.SecurityContextHolder
import org.springframework.security.crypto.password.PasswordEncoder
import org.springframework.security.web.context.HttpSessionSecurityContextRepository
import org.springframework.security.web.csrf.CsrfToken
import org.springframework.web.bind.annotation.GetMapping
import org.springframework.web.bind.annotation.PatchMapping
import org.springframework.web.bind.annotation.PathVariable
import org.springframework.web.bind.annotation.PostMapping
import org.springframework.web.bind.annotation.RequestBody
import org.springframework.web.bind.annotation.RequestMapping
import org.springframework.web.bind.annotation.ResponseStatus
import org.springframework.web.bind.annotation.RestController
import org.springframework.web.server.ResponseStatusException
import java.util.UUID
import javax.servlet.http.HttpServletRequest

data class LoginRequest(val username: String, val password: String)
data class UserView(val id: UUID, val username: String, val role: Role, val displayName: String,
    val groupId: UUID?, val locked: Boolean, val enabled: Boolean) {
    companion object { fun from(account: AuthAccount) = UserView(account.id, account.username, account.role,
        account.displayName, account.groupId, account.locked, account.enabled) }
}
data class CreateGroupRequest(val name: String)
data class CreateUserRequest(val username: String, val password: String, val role: Role,
    val displayName: String, val groupId: UUID? = null)
data class SetLockedRequest(val locked: Boolean)
data class SetRoleRequest(val role: Role, val groupId: UUID? = null)

@RestController
@RequestMapping("/api/auth")
@ConditionalOnProperty(name = ["core.auth.enabled"], havingValue = "true")
class AuthController(private val manager: AuthenticationManager, private val accounts: AccountRepository,
    private val audit: AuthAuditRepository) {
    @GetMapping("/csrf")
    fun csrf(token: CsrfToken): Map<String, String> = mapOf("token" to token.token, "headerName" to token.headerName)

    @PostMapping("/login")
    fun login(@RequestBody body: LoginRequest, request: HttpServletRequest): UserView {
        val username = body.username.trim().lowercase()
        val authentication = try {
            manager.authenticate(UsernamePasswordAuthenticationToken(username, body.password))
        } catch (_: AuthenticationException) {
            audit.append(AuthAudit(null, "LOGIN", null, "DENIED", request.getAttribute("requestId")?.toString()))
            throw ResponseStatusException(HttpStatus.UNAUTHORIZED, "Неверные учётные данные")
        }
        request.getSession(false)?.let { request.changeSessionId() }
        val context = SecurityContextHolder.createEmptyContext().also { it.authentication = authentication }
        SecurityContextHolder.setContext(context)
        request.getSession(true).setAttribute(HttpSessionSecurityContextRepository.SPRING_SECURITY_CONTEXT_KEY, context)
        val account = accounts.findByUsername(username) ?: throw BadCredentialsException("Учётная запись не найдена")
        audit.append(AuthAudit(account.id, "LOGIN", account.id, "OK", request.getAttribute("requestId")?.toString()))
        return UserView.from(account)
    }

    @GetMapping("/me")
    fun me(): UserView {
        val username = SecurityContextHolder.getContext().authentication?.name
            ?: throw ResponseStatusException(HttpStatus.UNAUTHORIZED)
        return UserView.from(accounts.findByUsername(username) ?: throw ResponseStatusException(HttpStatus.UNAUTHORIZED))
    }

    @PostMapping("/logout")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    fun logout(request: HttpServletRequest) {
        val actor = SecurityContextHolder.getContext().authentication?.name?.let(accounts::findByUsername)?.id
        audit.append(AuthAudit(actor, "LOGOUT", actor, "OK", request.getAttribute("requestId")?.toString()))
        request.getSession(false)?.invalidate()
        SecurityContextHolder.clearContext()
    }
}

@RestController
@RequestMapping("/api/admin")
@ConditionalOnProperty(name = ["core.auth.enabled"], havingValue = "true")
class AccountAdminController(private val accounts: AccountRepository, private val groups: GroupRepository,
    private val encoder: PasswordEncoder, private val audit: AuthAuditRepository) {
    @GetMapping("/groups") fun groups(): List<TrainingGroup> = groups.findAll()
    @GetMapping("/users") fun users(): List<UserView> = accounts.findAll().map(UserView::from)

    @PostMapping("/groups")
    @ResponseStatus(HttpStatus.CREATED)
    fun createGroup(@RequestBody body: CreateGroupRequest): TrainingGroup {
        require(body.name.trim().length in 2..120) { "Название группы должно содержать 2–120 символов" }
        return TrainingGroup(UUID.randomUUID(), body.name.trim()).also(groups::insert)
    }

    @PostMapping("/users")
    @ResponseStatus(HttpStatus.CREATED)
    fun createUser(@RequestBody body: CreateUserRequest, request: HttpServletRequest): UserView {
        val username = body.username.trim().lowercase()
        require(username.matches(Regex("[a-z0-9_.-]{3,80}"))) { "Некорректное имя пользователя" }
        require(body.password.length >= 12) { "Пароль должен содержать не менее 12 символов" }
        require(body.displayName.trim().length in 1..160) { "Укажите имя для отображения" }
        validateGroup(body.role, body.groupId)
        val account = AuthAccount(UUID.randomUUID(), username, encoder.encode(body.password), body.role,
            body.displayName.trim(), body.groupId)
        accounts.insert(account)
        audit.append(AuthAudit(actorId(), "USER_CREATED", account.id, "OK", request.getAttribute("requestId")?.toString()))
        return UserView.from(account)
    }

    @PatchMapping("/users/{id}/lock")
    fun lock(@PathVariable id: UUID, @RequestBody body: SetLockedRequest, request: HttpServletRequest): UserView {
        val account = accounts.findById(id) ?: throw NoSuchElementException("Учётная запись не найдена")
        if (body.locked && account.id == actorId()) throw IllegalStateException("Нельзя заблокировать собственную учётную запись")
        val updated = account.copy(locked = body.locked)
        accounts.update(updated)
        audit.append(AuthAudit(actorId(), if (body.locked) "USER_LOCKED" else "USER_UNLOCKED", id, "OK",
            request.getAttribute("requestId")?.toString()))
        return UserView.from(updated)
    }

    @PatchMapping("/users/{id}/role")
    fun setRole(@PathVariable id: UUID, @RequestBody body: SetRoleRequest, request: HttpServletRequest): UserView {
        val account = accounts.findById(id) ?: throw NoSuchElementException("Учётная запись не найдена")
        if (account.id == actorId() && body.role != Role.ADMIN) throw IllegalStateException("Нельзя снять собственные права админа")
        validateGroup(body.role, body.groupId)
        val updated = account.copy(role = body.role, groupId = body.groupId)
        accounts.update(updated)
        audit.append(AuthAudit(actorId(), "ROLE_CHANGED", id, "OK", request.getAttribute("requestId")?.toString()))
        return UserView.from(updated)
    }

    private fun validateGroup(role: Role, groupId: UUID?) {
        if (role != Role.ADMIN) {
            require(groupId != null && groups.findById(groupId) != null) { "Для преподавателя и студента нужна существующая группа" }
        } else require(groupId == null) { "Администратор не привязан к группе" }
    }

    private fun actorId(): UUID? = SecurityContextHolder.getContext().authentication?.name
        ?.let(accounts::findByUsername)?.id
}
