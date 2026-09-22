package ru.sirena112.core.dispatch

import org.springframework.beans.factory.annotation.Value
import org.springframework.context.annotation.Bean
import org.springframework.context.annotation.Configuration
import ru.sirena112.core.classifier.CalculationStatus
import ru.sirena112.core.domain.*
import java.time.Clock
import java.util.UUID

interface ServiceAssignmentRepository {
    fun save(assignment: ServiceAssignment): ServiceAssignment
    fun findById(id: UUID): ServiceAssignment?
    fun findBySessionId(sessionId: UUID): List<ServiceAssignment>
    fun existsBySessionId(sessionId: UUID): Boolean
}

class InMemoryServiceAssignmentRepository : ServiceAssignmentRepository {
    private val assignments = linkedMapOf<UUID, ServiceAssignment>()

    @Synchronized override fun save(assignment: ServiceAssignment): ServiceAssignment = assignment.also { assignments[it.id] = it }
    @Synchronized override fun findById(id: UUID): ServiceAssignment? = assignments[id]
    @Synchronized override fun findBySessionId(sessionId: UUID): List<ServiceAssignment> =
        assignments.values.filter { it.sessionId == sessionId }
    @Synchronized override fun existsBySessionId(sessionId: UUID): Boolean = assignments.values.any { it.sessionId == sessionId }
}

/** In-memory учебная реализация: состояние записывается до публикации события. */
class ServiceAssignmentService(
    private val sessions: TrainingSessionRepository,
    private val events: SessionEventRepository,
    private val clock: Clock = Clock.systemUTC(),
    private val deadlineSeconds: Long = 3600,
    private val repository: ServiceAssignmentRepository = InMemoryServiceAssignmentRepository()
) {
    init { require(deadlineSeconds > 0) { "Срок реагирования должен быть положительным" } }

    /** Фиксируем один набор адресатов отправленной карточки, не каждого черновика. */
    @Synchronized
    fun assignSubmittedCard(sessionId: UUID): List<ServiceAssignment> {
        val session = requireSession(sessionId)
        if (repository.existsBySessionId(sessionId)) return repository.findBySessionId(sessionId)
        check(session.state in setOf(SessionState.ACTIVE, SessionState.COMPLETED)) {
            "Назначения доступны только при отправке карточки"
        }
        val calculation = checkNotNull(session.operatorCard.calculation) { "Карточка ещё не рассчитана" }
        check(calculation.status == CalculationStatus.RESOLVED && calculation.missingInputIds.isEmpty()) {
            "Маршрутизация карточки ещё не завершена"
        }
        val timestamp = clock.instant()
        val created = calculation.services.distinctBy { it.id }.map { service ->
            ServiceAssignment(
                id = UUID.randomUUID(), sessionId = sessionId, serviceId = service.id,
                displayName = service.displayName, cardRevision = session.cardRevision,
                status = ServiceStatus.ADDED, createdAt = timestamp, updatedAt = timestamp,
                deadlineAt = timestamp.plusSeconds(deadlineSeconds),
                history = listOf(ServiceStatusEntry(UUID.randomUUID(), 1, null, ServiceStatus.ADDED,
                    timestamp, AssignmentSource.SYSTEM))
            )
        }
        created.forEach(repository::save)
        created.forEach { publish(it, SessionEventType.SERVICE_ASSIGNED) }
        return repository.findBySessionId(sessionId)
    }

    @Synchronized
    fun list(sessionId: UUID): List<ServiceAssignment> {
        requireSession(sessionId)
        val now = clock.instant()
        return repository.findBySessionId(sessionId).map {
            // Флаг просрочки не заменяет статус и не дописывает фиктивный переход.
            it.copy(overdue = !it.status.terminal && !now.isBefore(it.deadlineAt))
        }
    }

    @Synchronized
    fun changeStatus(sessionId: UUID, assignmentId: UUID, request: ChangeServiceStatusRequest): ServiceAssignment {
        requireSession(sessionId)
        val current = repository.findById(assignmentId)?.takeIf { it.sessionId == sessionId }
            ?: throw NoSuchElementException("Назначение службы $assignmentId не найдено")
        require((request.comment?.length ?: 0) <= 2000) { "Комментарий длиннее 2000 символов" }
        require((request.refusalReason?.length ?: 0) <= 2000) { "Причина отказа длиннее 2000 символов" }
        require(request.status != ServiceStatus.REFUSED || !request.refusalReason.isNullOrBlank()) {
            "При отказе обязательна причина"
        }
        require(request.status == ServiceStatus.REFUSED || request.refusalReason == null) {
            "Причина отказа допустима только для REFUSED"
        }
        // Та же блокировка, что у in-memory event repository: коллизия eventId не меняет историю.
        synchronized(events) {
            check(events.findById(request.eventId) == null) { "Повторный eventId ${request.eventId}" }
            check(current.status.canTransitionTo(request.status)) {
                "Недопустимый переход ${current.status} -> ${request.status}"
            }
            val timestamp = maxOf(clock.instant(), current.updatedAt)
            val entry = ServiceStatusEntry(request.eventId, current.history.size + 1,
                current.status, request.status, timestamp, AssignmentSource.MOCK,
                request.comment, request.refusalReason)
            val updated = current.copy(status = request.status, updatedAt = timestamp,
                history = current.history + entry)
            repository.save(updated)
            publish(updated, SessionEventType.SERVICE_STATUS_CHANGED)
        }
        return list(sessionId).first { it.id == assignmentId }
    }

    private fun publish(assignment: ServiceAssignment, type: SessionEventType) {
        val entry = assignment.history.last()
        check(events.saveIfAbsent(SessionEvent.create(
            assignment.sessionId, type, EventSource.CORE,
            mapOf("assignmentId" to assignment.id, "serviceId" to assignment.serviceId,
                "cardRevision" to assignment.cardRevision, "deadlineAt" to assignment.deadlineAt,
                "sequence" to entry.sequence, "fromStatus" to entry.fromStatus,
                "status" to entry.status, "changeSource" to entry.source,
                "comment" to entry.comment, "refusalReason" to entry.refusalReason),
            eventId = entry.eventId, timestamp = entry.timestamp
        ))) { "Повторный eventId ${entry.eventId}" }
    }

    private fun requireSession(id: UUID): TrainingSession = sessions.findById(id)
        ?: throw NoSuchElementException("Учебная сессия $id не найдена")
}

@Configuration
class ServiceAssignmentConfiguration {
    @Bean
    fun serviceAssignmentService(
        sessions: TrainingSessionRepository,
        events: SessionEventRepository,
        repository: ServiceAssignmentRepository,
        @Value("\${core.service-assignments.deadline-seconds:3600}") deadlineSeconds: Long
    ): ServiceAssignmentService = ServiceAssignmentService(sessions, events, deadlineSeconds = deadlineSeconds, repository = repository)

    @Bean
    @org.springframework.boot.autoconfigure.condition.ConditionalOnProperty(
        name = ["core.storage"], havingValue = "in-memory", matchIfMissing = true
    )
    fun serviceAssignmentRepository(): ServiceAssignmentRepository = InMemoryServiceAssignmentRepository()
}
