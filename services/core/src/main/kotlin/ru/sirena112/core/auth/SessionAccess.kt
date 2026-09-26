package ru.sirena112.core.auth

import org.springframework.beans.factory.annotation.Value
import org.springframework.http.HttpStatus
import org.springframework.security.core.context.SecurityContextHolder
import org.springframework.stereotype.Service
import org.springframework.web.server.ResponseStatusException
import ru.sirena112.core.domain.TrainingSession
import ru.sirena112.core.domain.TrainingSessionRepository
import java.util.UUID

/** Ownership checks are shared by REST and the WebSocket handshake. */
@Service
class SessionAccess(
    private val accounts: AccountRepository,
    private val sessions: TrainingSessionRepository,
    private val audit: AuthAuditRepository,
    @Value("\${core.auth.enabled:false}") private val enabled: Boolean
) {
    fun current(): AuthAccount? {
        if (!enabled) return null
        val authentication = SecurityContextHolder.getContext().authentication
            ?: throw ResponseStatusException(HttpStatus.UNAUTHORIZED)
        val account = accounts.findByUsername(authentication.name)
            ?: throw ResponseStatusException(HttpStatus.UNAUTHORIZED)
        if (!authentication.isAuthenticated || account.locked || !account.enabled ||
            authentication.authorities.none { it.authority == "ROLE_${account.role.name}" }) {
            deny(account, null)
        }
        return account
    }

    fun assignment(studentId: UUID?): Triple<UUID?, UUID?, UUID?> {
        val teacher = current() ?: return Triple(null, null, null)
        if (teacher.role != Role.TEACHER || teacher.groupId == null) deny(teacher, null)
        val student = studentId?.let(accounts::findById)
        if (student == null || student.role != Role.STUDENT || student.locked || !student.enabled ||
            student.groupId != teacher.groupId) deny(teacher, studentId)
        return Triple(student.id, teacher.id, teacher.groupId)
    }

    fun studentOwns(sessionId: UUID) {
        val student = current() ?: return
        val session = session(sessionId)
        if (student.role != Role.STUDENT || session.studentId != student.id) deny(student, sessionId)
    }

    fun teacherCanRead(sessionId: UUID) = teacherAccess(sessionId, false)
    fun teacherCanWrite(sessionId: UUID) = teacherAccess(sessionId, true)

    private fun teacherAccess(sessionId: UUID, write: Boolean) {
        val actor = current() ?: return
        val session = session(sessionId)
        val permitted = when (actor.role) {
            Role.ADMIN -> !write
            Role.TEACHER -> actor.groupId != null && session.groupId == actor.groupId
            Role.STUDENT -> false
        }
        if (!permitted) deny(actor, sessionId)
    }

    fun canSeeAssignment(session: TrainingSession): Boolean {
        val actor = current() ?: return true
        return actor.role == Role.STUDENT && session.studentId == actor.id
    }

    fun websocket(sessionId: UUID) {
        val actor = current() ?: return
        val session = session(sessionId)
        val permitted = when (actor.role) {
            Role.ADMIN -> true
            Role.TEACHER -> actor.groupId != null && session.groupId == actor.groupId
            Role.STUDENT -> session.studentId == actor.id
        }
        if (!permitted) deny(actor, sessionId)
    }

    private fun session(id: UUID): TrainingSession = sessions.findById(id)
        ?: throw ResponseStatusException(HttpStatus.NOT_FOUND, "Занятие не найдено")

    private fun deny(actor: AuthAccount, subject: UUID?): Nothing {
        audit.append(AuthAudit(actor.id, "ACCESS_DENIED", subject, "DENIED", null))
        throw ResponseStatusException(HttpStatus.FORBIDDEN, "Нет доступа")
    }
}
