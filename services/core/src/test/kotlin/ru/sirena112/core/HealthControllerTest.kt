package ru.sirena112.core

import org.junit.jupiter.api.Test
import org.springframework.beans.factory.annotation.Autowired
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc
import org.springframework.boot.test.context.SpringBootTest
import org.springframework.test.web.servlet.MockMvc
import org.springframework.test.web.servlet.get

@SpringBootTest
@AutoConfigureMockMvc
class HealthControllerTest {

    @Autowired
    lateinit var mockMvc: MockMvc

    @Test
    fun `live endpoint returns service status and request id`() {
        mockMvc.get("/health/live")
            .andExpect { status { isOk() } }
            .andExpect { header { exists("X-Request-ID") } }
            .andExpect { jsonPath("$.status") { value("UP") } }
    }

    @Test
    fun `ready endpoint exposes current checks`() {
        mockMvc.get("/health/ready")
            .andExpect { status { isOk() } }
            .andExpect { jsonPath("$.checks.http") { value("UP") } }
            .andExpect { jsonPath("$.checks.database") { value("NOT_CONFIGURED") } }
    }

    @Test
    fun `unknown endpoint returns unified error`() {
        mockMvc.get("/does-not-exist")
            .andExpect { status { isNotFound() } }
            .andExpect { jsonPath("$.code") { value("NOT_FOUND") } }
            .andExpect { jsonPath("$.requestId") { exists() } }
    }
}
