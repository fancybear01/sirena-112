package ru.sirena112.core.integration

import org.springframework.boot.web.client.RestTemplateBuilder
import org.springframework.context.annotation.Bean
import org.springframework.context.annotation.Configuration
import org.springframework.beans.factory.annotation.Qualifier
import org.springframework.http.converter.json.MappingJackson2HttpMessageConverter
import com.fasterxml.jackson.databind.ObjectMapper
import ru.sirena112.core.config.CoreProperties
import java.time.Duration

/**
 * Клиенты внешних сервисов.
 *
 * Таймауты намеренно короткие: если AI не ответил за пару секунд, занятие
 * должно продолжиться на упрощённом отчёте Core, а не ждать. Во время
 * демонстрации это важнее точности оценки.
 */
@Configuration
class IntegrationConfiguration {

    @Bean
    fun aiRestTemplate(builder: RestTemplateBuilder, objectMapper: ObjectMapper) =
        builder
            .setConnectTimeout(Duration.ofMillis(CONNECT_TIMEOUT_MS))
            .setReadTimeout(Duration.ofMillis(READ_TIMEOUT_MS))
            .additionalMessageConverters(MappingJackson2HttpMessageConverter(objectMapper))
            .build()

    @Bean
    fun aiClient(
        @Qualifier("aiRestTemplate") aiRestTemplate: org.springframework.web.client.RestTemplate,
        properties: CoreProperties
    ): AiClient = HttpAiClient(aiRestTemplate, properties)

    @Bean
    fun mediaRestTemplate(builder: RestTemplateBuilder, objectMapper: ObjectMapper) =
        builder
            .setConnectTimeout(Duration.ofMillis(CONNECT_TIMEOUT_MS))
            .setReadTimeout(Duration.ofMillis(READ_TIMEOUT_MS))
            .additionalMessageConverters(MappingJackson2HttpMessageConverter(objectMapper))
            .build()

    @Bean
    fun mediaClient(
        @Qualifier("mediaRestTemplate") mediaRestTemplate: org.springframework.web.client.RestTemplate,
        properties: CoreProperties
    ): MediaClient = when (properties.mediaMode.lowercase()) {
        "http" -> HttpMediaClient(mediaRestTemplate, properties)
        "mock" -> MockMediaClient()
        else -> throw IllegalArgumentException("CORE_MEDIA_MODE должен быть http или mock")
    }

    private companion object {
        const val CONNECT_TIMEOUT_MS = 500L
        const val READ_TIMEOUT_MS = 3000L
    }
}
