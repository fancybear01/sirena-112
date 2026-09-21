package ru.sirena112.core.dispatch

import java.time.Instant
import java.util.UUID

enum class ServiceStatus {
    ADDED, RECEIVED, ACCEPTED, RESPONDING, ARRIVED, COMPLETED, REFUSED, FAILED;

    val terminal: Boolean get() = this in setOf(COMPLETED, REFUSED, FAILED)

    fun canTransitionTo(next: ServiceStatus): Boolean = next in when (this) {
        ADDED -> setOf(RECEIVED, FAILED)
        RECEIVED -> setOf(ACCEPTED, REFUSED, FAILED)
        ACCEPTED -> setOf(RESPONDING, REFUSED, FAILED)
        RESPONDING -> setOf(ARRIVED, FAILED)
        ARRIVED -> setOf(COMPLETED, FAILED)
        COMPLETED, REFUSED, FAILED -> emptySet()
    }
}

enum class AssignmentSource { SYSTEM, MOCK, TEACHER, SERVICE }

data class ServiceStatusEntry(
    val eventId: UUID,
    val sequence: Int,
    val fromStatus: ServiceStatus?,
    val status: ServiceStatus,
    val timestamp: Instant,
    val source: AssignmentSource,
    val comment: String? = null,
    val refusalReason: String? = null
)

data class ServiceAssignment(
    val id: UUID,
    val sessionId: UUID,
    val serviceId: String,
    val displayName: String,
    val cardRevision: Int,
    val status: ServiceStatus,
    val createdAt: Instant,
    val updatedAt: Instant,
    val deadlineAt: Instant,
    val history: List<ServiceStatusEntry>,
    val overdue: Boolean = false
)

data class ChangeServiceStatusRequest(
    val eventId: UUID,
    val status: ServiceStatus,
    val comment: String? = null,
    val refusalReason: String? = null
)
