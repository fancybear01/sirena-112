package ru.sirena112.core

import org.springframework.boot.autoconfigure.SpringBootApplication
import org.springframework.boot.context.properties.EnableConfigurationProperties
import org.springframework.boot.runApplication
import ru.sirena112.core.config.CoreProperties

@SpringBootApplication
@EnableConfigurationProperties(CoreProperties::class)
class CoreApplication

fun main(args: Array<String>) {
    runApplication<CoreApplication>(*args)
}
