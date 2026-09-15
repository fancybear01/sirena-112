package ru.sirena112.core.web

import org.springframework.http.ResponseEntity
import org.springframework.web.bind.annotation.GetMapping
import org.springframework.web.bind.annotation.RequestMapping
import org.springframework.web.bind.annotation.RestController
import ru.sirena112.core.config.CoreProperties

@RestController
@RequestMapping("/health")
class HealthController(private val properties: CoreProperties) {

    @GetMapping("/live")
    fun live(): HealthResponse = HealthResponse(
        status = "UP",
        service = "sirena-core",
        version = properties.version,
        environment = properties.environment
    )

    @GetMapping("/ready")
    fun ready(): ResponseEntity<HealthResponse> = ResponseEntity.ok(
        HealthResponse(
            status = "UP",
            service = "sirena-core",
            version = properties.version,
            environment = properties.environment,
            checks = mapOf("http" to "UP", "database" to "NOT_CONFIGURED")
        )
    )
}

data class HealthResponse(
    val status: String,
    val service: String,
    val version: String,
    val environment: String,
    val checks: Map<String, String> = emptyMap()
)
