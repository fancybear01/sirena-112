package ru.sirena112.core.dispatch

import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty
import org.springframework.web.bind.annotation.*
import java.util.UUID

@RestController
class ServiceAssignmentController(private val assignments: ServiceAssignmentService) {
    @GetMapping("/api/student/sessions/{sessionId}/service-assignments",
        "/api/teacher/sessions/{sessionId}/service-assignments")
    fun list(@PathVariable sessionId: UUID): List<ServiceAssignment> = assignments.list(sessionId)
}

/** Отключён по умолчанию. Не является интеграцией с реальными ведомствами. */
@RestController
@ConditionalOnProperty(name = ["core.service-assignments.mock-updates-enabled"], havingValue = "true")
class MockServiceAssignmentController(private val assignments: ServiceAssignmentService) {
    @PostMapping("/api/mock/sessions/{sessionId}/service-assignments/{assignmentId}/status")
    fun change(@PathVariable sessionId: UUID, @PathVariable assignmentId: UUID,
        @RequestBody request: ChangeServiceStatusRequest): ServiceAssignment =
        assignments.changeStatus(sessionId, assignmentId, request)
}
