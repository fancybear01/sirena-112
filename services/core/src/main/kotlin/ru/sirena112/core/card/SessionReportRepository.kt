package ru.sirena112.core.card

import java.util.UUID
import java.util.concurrent.ConcurrentHashMap

/** Durable report boundary: reports survive a Core restart together with the session. */
interface SessionReportRepository {
    fun save(report: SessionReport): SessionReport
    fun findBySessionIdOrNull(sessionId: UUID): SessionReport?
    fun findAll(): List<SessionReport>
    fun findBySessionId(sessionId: UUID): SessionReport = findBySessionIdOrNull(sessionId)
        ?: throw NoSuchElementException("Отчёт для сессии $sessionId ещё не сформирован")
}

class InMemorySessionReportRepository : SessionReportRepository {
    private val reports = ConcurrentHashMap<UUID, SessionReport>()
    override fun save(report: SessionReport): SessionReport = report.also { reports[it.sessionId] = it }
    override fun findBySessionIdOrNull(sessionId: UUID): SessionReport? = reports[sessionId]
    override fun findAll(): List<SessionReport> = reports.values.toList()
}
