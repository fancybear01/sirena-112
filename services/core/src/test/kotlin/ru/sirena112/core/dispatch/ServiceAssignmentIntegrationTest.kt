package ru.sirena112.core.dispatch

import com.fasterxml.jackson.databind.JsonNode
import com.fasterxml.jackson.databind.ObjectMapper
import org.junit.jupiter.api.Assertions.*
import org.junit.jupiter.api.Test
import org.springframework.beans.factory.annotation.Autowired
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc
import org.springframework.boot.test.context.SpringBootTest
import org.springframework.boot.test.web.server.LocalServerPort
import org.springframework.http.MediaType
import org.springframework.test.web.servlet.MockMvc
import org.springframework.test.web.servlet.get
import org.springframework.test.web.servlet.post
import org.springframework.web.socket.TextMessage
import org.springframework.web.socket.WebSocketSession
import org.springframework.web.socket.client.standard.StandardWebSocketClient
import org.springframework.web.socket.handler.TextWebSocketHandler
import ru.sirena112.core.card.*
import ru.sirena112.core.classifier.*
import java.util.UUID
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.TimeUnit

@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT,
    properties = ["core.service-assignments.mock-updates-enabled=true"])
@AutoConfigureMockMvc
class ServiceAssignmentIntegrationTest {
    @Autowired lateinit var facade: CardTrainingFacade
    @Autowired lateinit var assignments: ServiceAssignmentService
    @Autowired lateinit var mvc: MockMvc
    @Autowired lateinit var mapper: ObjectMapper
    @LocalServerPort var port: Int = 0

    @Test
    fun `submit creates assignments API preserves history and websocket delivers changes`() {
        val session = facade.createSession(CreateCardSessionRequest())
        facade.start(session.id)
        val input = ContractTestSupport.objectMapper.convertValue(
            ContractTestSupport.fixtureNode("scenario-1050602.json").at("/groundTruth/expectedInput"),
            OperatorCardInput::class.java)
        facade.saveCard(session.id, SaveCardRequest(input))
        assertTrue(assignments.list(session.id).isEmpty())
        val messages = LinkedBlockingQueue<JsonNode>()
        val socket = StandardWebSocketClient().doHandshake(object : TextWebSocketHandler() {
            override fun handleTextMessage(session: WebSocketSession, message: TextMessage) {
                val node = mapper.readTree(message.payload)
                if (node["type"].asText().startsWith("service.")) messages.add(node)
            }
        }, "ws://localhost:$port/ws/sessions/${session.id}/events").get(10, TimeUnit.SECONDS)
        try {
            facade.submit(session.id, SubmitCardRequest(input))
            val all = assignments.list(session.id)
            assertEquals(14, all.size)
            repeat(14) { assertEquals("service.assigned", messages.poll(5, TimeUnit.SECONDS)?.get("type")?.asText()) }
            val assignment = all.first()
            val path = "/api/mock/sessions/${session.id}/service-assignments/${assignment.id}/status"
            val request = ChangeServiceStatusRequest(UUID.randomUUID(), ServiceStatus.RECEIVED, "Получено")
            mvc.post(path) { contentType = MediaType.APPLICATION_JSON; content = mapper.writeValueAsString(request) }
                .andExpect { status { isOk() }; jsonPath("$.history.length()") { value(2) } }
            val event = messages.poll(5, TimeUnit.SECONDS)!!
            assertEquals("service.status_changed", event["type"].asText())
            assertEquals(request.eventId.toString(), event["eventId"].asText())
            assertEquals("RECEIVED", event.at("/payload/status").asText())
            assertEquals("core", event["source"].asText())
            assertFalse(event["timestamp"].asText().isBlank())
            mvc.post(path) { contentType = MediaType.APPLICATION_JSON; content = mapper.writeValueAsString(request) }
                .andExpect { status { isConflict() } }
            mvc.post(path) { contentType = MediaType.APPLICATION_JSON
                content = mapper.writeValueAsString(request.copy(eventId = UUID.randomUUID(), status = ServiceStatus.ARRIVED))
            }.andExpect { status { isConflict() } }
            mvc.post(path) { contentType = MediaType.APPLICATION_JSON
                content = mapper.writeValueAsString(request.copy(eventId = UUID.randomUUID(), status = ServiceStatus.REFUSED))
            }.andExpect { status { isBadRequest() } }
            listOf("teacher", "student").forEach { role ->
                mvc.get("/api/$role/sessions/${session.id}/service-assignments").andExpect {
                    status { isOk() }; jsonPath("$[0].status") { value("RECEIVED") }
                    jsonPath("$[0].history.length()") { value(2) }
                    jsonPath("$[1].status") { value("ADDED") }
                }
            }
            mvc.get("/api/student/sessions/${UUID.randomUUID()}/service-assignments")
                .andExpect { status { isNotFound() } }
            assertEquals("SCORED", facade.get(session.id).state.name)
            assertTrue(messages.isEmpty())
        } finally { socket.close() }
    }
}

@SpringBootTest
@AutoConfigureMockMvc
class ServiceAssignmentMockDisabledTest {
    @Autowired lateinit var mvc: MockMvc

    @Test
    fun `mock endpoint disabled by default`() {
        mvc.post("/api/mock/sessions/${UUID.randomUUID()}/service-assignments/${UUID.randomUUID()}/status") {
            contentType = MediaType.APPLICATION_JSON
            content = """{"eventId":"${UUID.randomUUID()}","status":"RECEIVED"}"""
        }.andExpect { status { isNotFound() } }
    }
}
