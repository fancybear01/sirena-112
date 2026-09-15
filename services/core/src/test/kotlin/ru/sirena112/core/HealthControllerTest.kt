package ru.sirena112.core

import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Test
import org.springframework.beans.factory.annotation.Autowired
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc
import org.springframework.boot.test.context.SpringBootTest
import org.springframework.test.web.servlet.MockMvc
import org.springframework.test.web.servlet.get
import ru.sirena112.core.config.CoreProperties

@SpringBootTest
@AutoConfigureMockMvc
class HealthControllerTest {

    @Autowired
    lateinit var mockMvc: MockMvc

    @Autowired
    lateinit var properties: CoreProperties

    @Test
    fun `live endpoint returns service status and request id`() {
        mockMvc.get("/health") {
            header("X-Session-ID", "session-test-1")
        }
            .andExpect { status { isOk() } }
            .andExpect { header { exists("X-Request-ID") } }
            .andExpect { jsonPath("$.status") { value("UP") } }

        mockMvc.get("/health/live")
            .andExpect { status { isOk() } }
    }

    @Test
    fun `ready endpoint exposes current checks`() {
        mockMvc.get("/health/ready")
            .andExpect { status { isOk() } }
            .andExpect { jsonPath("$.checks.http") { value("UP") } }
            .andExpect { jsonPath("$.checks.database") { value("NOT_CONFIGURED") } }

        mockMvc.get("/ready")
            .andExpect { status { isOk() } }
    }

    @Test
    fun `unknown endpoint returns unified error`() {
        mockMvc.get("/does-not-exist")
            .andExpect { status { isNotFound() } }
            .andExpect { jsonPath("$.code") { value("NOT_FOUND") } }
            .andExpect { jsonPath("$.requestId") { exists() } }
    }

    @Test
    fun `AI and Media URLs bind from environment-backed configuration`() {
        assertEquals("http://localhost:8090", properties.aiBaseUrl)
        assertEquals("http://localhost:8091", properties.mediaBaseUrl)
    }
}
