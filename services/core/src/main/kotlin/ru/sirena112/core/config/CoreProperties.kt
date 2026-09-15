package ru.sirena112.core.config

import org.springframework.boot.context.properties.ConfigurationProperties

@ConfigurationProperties(prefix = "core")
data class CoreProperties(
    var environment: String = "local",
    var version: String = "dev",
    var aiBaseUrl: String = "http://localhost:8090",
    var mediaBaseUrl: String = "http://localhost:8091"
)
