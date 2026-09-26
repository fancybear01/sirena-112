package ru.sirena112.core.integration

import com.fasterxml.jackson.databind.ObjectMapper
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import org.mockito.ArgumentMatchers.any
import org.mockito.Mockito.doAnswer
import org.mockito.Mockito.mock
import org.mockito.Mockito.`when`
import org.springframework.beans.factory.annotation.Autowired
import org.springframework.beans.factory.annotation.Qualifier
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc
import org.springframework.boot.test.context.SpringBootTest
import org.springframework.http.HttpMethod
import org.springframework.http.HttpStatus
import org.springframework.http.MediaType
import org.springframework.test.web.client.MockRestServiceServer
import org.springframework.test.web.client.match.MockRestRequestMatchers.content
import org.springframework.test.web.client.match.MockRestRequestMatchers.method
import org.springframework.test.web.client.match.MockRestRequestMatchers.requestTo
import org.springframework.test.web.client.response.MockRestResponseCreators.withStatus
import org.springframework.test.web.client.response.MockRestResponseCreators.withSuccess
import org.springframework.test.web.servlet.MockMvc
import org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get
import org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post
import org.springframework.test.web.servlet.result.MockMvcResultMatchers.status
import org.springframework.web.client.ResourceAccessException
import org.springframework.web.client.RestTemplate
import org.springframework.web.socket.CloseStatus
import org.springframework.web.socket.TextMessage
import org.springframework.web.socket.WebSocketSession
import ru.sirena112.core.card.CardTrainingFacade
import ru.sirena112.core.card.CreateCardSessionRequest
import ru.sirena112.core.domain.EventSource
import ru.sirena112.core.domain.SessionEvent
import ru.sirena112.core.domain.SessionEventRepository
import ru.sirena112.core.domain.SessionEventSubscription
import ru.sirena112.core.domain.SessionEventType
import ru.sirena112.core.domain.SessionMode
import ru.sirena112.core.domain.SessionState
import ru.sirena112.core.events.SessionEventWebSocketHandler
import java.net.URI
import java.net.SocketTimeoutException
import java.util.UUID

/** Core's real HTTP adapters against the documented AI and Media wire contracts. */
@SpringBootTest(properties = [
    "core.ai-base-url=http://ai.contract",
    "core.media-base-url=http://media.contract",
    "core.media-mode=http"
])
@AutoConfigureMockMvc
class VoiceCrossServiceContractTest {
    @Autowired lateinit var facade: CardTrainingFacade
    @Autowired lateinit var mvc: MockMvc
    @Autowired lateinit var mapper: ObjectMapper
    @Autowired lateinit var events: SessionEventRepository
    @Autowired lateinit var subscriptions: SessionEventSubscription
    @Autowired @Qualifier("aiRestTemplate") lateinit var aiTemplate: RestTemplate
    @Autowired @Qualifier("mediaRestTemplate") lateinit var mediaTemplate: RestTemplate

    @Test
    fun `ids survive AI creation Media start ingest HTTP and WebSocket replay`() {
        val session = facade.createSession(CreateCardSessionRequest(mode = SessionMode.VOICE))
        val id = session.id
        val aiId = "voice-$id"
        val callId = "call-$id"
        val ai = MockRestServiceServer.createServer(aiTemplate)
        val media = MockRestServiceServer.createServer(mediaTemplate)
        ai.expect(requestTo("http://ai.contract/ai/voice/sessions"))
            .andExpect(method(HttpMethod.POST))
            .andExpect(content().json("""{"sessionId":"$id","scenario":{"id":"${session.scenarioId}"}}""", false))
            .andRespond(withSuccess("""{"aiSessionId":"$aiId","sessionId":"$id","scenarioId":"${session.scenarioId}"}""",
                MediaType.APPLICATION_JSON))
        media.expect(requestTo("http://media.contract/internal/v1/calls/start"))
            .andExpect(method(HttpMethod.POST))
            .andExpect(content().json("""{"sessionId":"$id","aiSessionId":"$aiId","sipAddress":"PJSIP/1001"}""", true))
            .andRespond(withStatus(HttpStatus.ACCEPTED).contentType(MediaType.APPLICATION_JSON)
                .body("""{"callId":"$callId","sessionId":"$id","aiSessionId":"$aiId","sipAddress":"PJSIP/1001","state":"RINGING"}"""))
        media.expect(requestTo("http://media.contract/internal/v1/calls/hangup"))
            .andExpect(method(HttpMethod.POST))
            .andExpect(content().json("""{"callId":"$callId","sessionId":"$id"}""", true))
            .andRespond(withSuccess("""{"callId":"$callId","sessionId":"$id","state":"ENDED"}""",
                MediaType.APPLICATION_JSON))
        ai.expect(requestTo("http://ai.contract/ai/voice/sessions/$aiId"))
            .andExpect(method(HttpMethod.DELETE)).andRespond(withStatus(HttpStatus.NO_CONTENT))

        val started = mvc.perform(post("/api/teacher/sessions/$id/call/start")
            .contentType(MediaType.APPLICATION_JSON).content("""{"sipAddress":"PJSIP/1001"}"""))
            .andExpect(status().isAccepted).andReturn()
        val call = mapper.readTree(started.response.contentAsString)
        assertEquals(id.toString(), call["sessionId"].asText())
        assertEquals(aiId, call["aiSessionId"].asText())
        assertEquals(callId, call["callId"].asText())

        val ringing = event(id, callId, aiId, SessionEventType.CALL_RINGING)
        val answered = event(id, callId, aiId, SessionEventType.CALL_ANSWERED)
        val transcript = event(id, callId, aiId, SessionEventType.TRANSCRIPT_FINAL, mapOf("text" to "Учебный адрес"))
        val ended = event(id, callId, aiId, SessionEventType.CALL_ENDED)
        assertTrue(deliver(ringing))
        assertFalse(deliver(ringing))
        mvc.perform(post("/internal/v1/media/events").contentType(MediaType.APPLICATION_JSON)
            .content(mapper.writeValueAsString(ringing.copy(payload = ringing.payload + ("text" to "other")))))
            .andExpect(status().isConflict)
        assertTrue(deliver(answered))
        assertTrue(deliver(transcript))

        mvc.perform(post("/api/teacher/sessions/$id/call/hangup")).andExpect(status().isOk)
        assertTrue(deliver(ended))
        assertFalse(deliver(ended))
        mvc.perform(post("/api/teacher/sessions/$id/call/hangup")).andExpect(status().isOk)
        assertEquals(SessionState.COMPLETED, facade.get(id).state)

        val replay = mvc.perform(get("/api/teacher/sessions/$id/events"))
            .andExpect(status().isOk).andReturn().response.contentAsString
        val httpIds = mapper.readTree(replay).map { it["eventId"].asText() }
        assertEquals(1, httpIds.count { it == ringing.eventId.toString() })
        assertEquals(1, httpIds.count { it == ended.eventId.toString() })
        assertTrue(httpIds.contains(transcript.eventId.toString()))

        val socket = mock(WebSocketSession::class.java)
        `when`(socket.id).thenReturn("voice-$id")
        `when`(socket.uri).thenReturn(URI("ws://localhost/ws/sessions/$id/events"))
        `when`(socket.isOpen).thenReturn(true)
        val wsIds = mutableListOf<String>()
        doAnswer { invocation ->
            wsIds += mapper.readTree(invocation.getArgument<TextMessage>(0).payload)["eventId"].asText()
            null
        }.`when`(socket).sendMessage(any())
        val handler = SessionEventWebSocketHandler(events, subscriptions, mapper)
        handler.afterConnectionEstablished(socket)
        handler.afterConnectionClosed(socket, CloseStatus.NORMAL)
        assertEquals(httpIds, wsIds)
        println("voice-contract sessionId=$id aiSessionId=$aiId callId=$callId events=${httpIds.size}")
        ai.verify()
        media.verify()
    }

    @Test
    fun `Media rejection releases AI and leaves voice retryable and card mode usable`() {
        for (failure in listOf(HttpStatus.CONFLICT, HttpStatus.SERVICE_UNAVAILABLE)) {
            val session = facade.createSession(CreateCardSessionRequest(mode = SessionMode.VOICE))
            val id = session.id
            val aiId = "voice-$id"
            val ai = MockRestServiceServer.createServer(aiTemplate)
            val media = MockRestServiceServer.createServer(mediaTemplate)
            ai.expect(requestTo("http://ai.contract/ai/voice/sessions"))
                .andRespond(withSuccess("""{"aiSessionId":"$aiId","sessionId":"$id","scenarioId":"${session.scenarioId}"}""",
                    MediaType.APPLICATION_JSON))
            media.expect(requestTo("http://media.contract/internal/v1/calls/start"))
                .andRespond(withStatus(failure))
            ai.expect(requestTo("http://ai.contract/ai/voice/sessions/$aiId"))
                .andExpect(method(HttpMethod.DELETE)).andRespond(withStatus(HttpStatus.NO_CONTENT))

            val expected = if (failure == HttpStatus.CONFLICT) 409 else 503
            assertEquals(expected, mvc.perform(post("/api/teacher/sessions/$id/call/start")
                .contentType(MediaType.APPLICATION_JSON).content("""{"sipAddress":"1001"}"""))
                .andReturn().response.status)
            assertEquals(SessionState.READY, facade.get(id).state)
            ai.verify()
            media.verify()
        }
        val card = facade.createSession(CreateCardSessionRequest())
        assertEquals(SessionState.ACTIVE, facade.start(card.id).state)
    }

    @Test
    fun `Media timeout returns 503 while keeping the session`() {
        val session = facade.createSession(CreateCardSessionRequest(mode = SessionMode.VOICE))
        val id = session.id
        val ai = MockRestServiceServer.createServer(aiTemplate)
        val media = MockRestServiceServer.createServer(mediaTemplate)
        ai.expect(requestTo("http://ai.contract/ai/voice/sessions"))
            .andRespond(withSuccess("""{"aiSessionId":"voice-$id","sessionId":"$id","scenarioId":"${session.scenarioId}"}""",
                MediaType.APPLICATION_JSON))
        media.expect(requestTo("http://media.contract/internal/v1/calls/start"))
            .andRespond { throw ResourceAccessException("Read timed out", SocketTimeoutException()) }
        val response = mvc.perform(post("/api/teacher/sessions/$id/call/start")
            .contentType(MediaType.APPLICATION_JSON).content("""{"sipAddress":"1001"}"""))
            .andExpect(status().isServiceUnavailable).andReturn()
        assertEquals("UPSTREAM_UNAVAILABLE", mapper.readTree(response.response.contentAsString)["code"].asText())
        assertTrue(mapper.readTree(response.response.contentAsByteArray)["message"].asText().contains("вовремя"))
        assertEquals(SessionState.READY, facade.get(id).state)
        ai.verify()
        media.verify()
    }

    private fun event(id: UUID, callId: String, aiId: String, type: SessionEventType,
                      extra: Map<String, Any?> = emptyMap()) = SessionEvent.create(
        id, type, EventSource.MEDIA, mapOf("callId" to callId, "aiSessionId" to aiId) + extra)

    private fun deliver(event: SessionEvent): Boolean {
        val response = mvc.perform(post("/internal/v1/media/events")
            .contentType(MediaType.APPLICATION_JSON).content(mapper.writeValueAsString(event)))
            .andExpect(status().isOk).andReturn()
        return mapper.readTree(response.response.contentAsString)["accepted"].asBoolean()
    }
}
