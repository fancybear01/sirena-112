package ru.sirena112.core.integration

import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertNotNull
import org.junit.jupiter.api.Assertions.assertThrows
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import org.springframework.beans.factory.annotation.Autowired
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc
import org.springframework.boot.test.context.SpringBootTest
import org.springframework.boot.test.context.TestConfiguration
import org.springframework.context.annotation.Bean
import org.springframework.context.annotation.Primary
import org.springframework.http.MediaType
import org.springframework.test.web.servlet.MockMvc
import org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post
import org.springframework.test.web.servlet.result.MockMvcResultMatchers.status
import ru.sirena112.core.card.CardTrainingFacade
import ru.sirena112.core.card.CreateCardSessionRequest
import ru.sirena112.core.domain.EventSource
import ru.sirena112.core.domain.Scenario
import ru.sirena112.core.domain.SessionEvent
import ru.sirena112.core.domain.SessionEventType
import ru.sirena112.core.domain.SessionMode
import ru.sirena112.core.domain.SessionState
import java.util.UUID

@SpringBootTest
@AutoConfigureMockMvc
class VoiceTrainingIntegrationTest {
    class FakeAi : AiClient {
        val closed = mutableListOf<String>()
        override fun createSession(sessionId: UUID, scenario: Scenario) = AiSessionHandle("voice-$sessionId")
        override fun closeSession(aiSessionId: String) { closed += aiSessionId }
        override fun score(command: AiScoreCommand): AiScoreReport? = null
    }

    class FakeMedia : MediaClient {
        var failStart = false
        override fun startCall(command: MediaCallCommand): MediaCallHandle {
            if (failStart) throw UpstreamUnavailableException("Media unavailable")
            return MediaCallHandle("call-${command.sessionId}", command.sessionId,
                command.aiSessionId, command.destination, "RINGING")
        }
        override fun hangup(callId: String, sessionId: UUID) =
            MediaCallHandle(callId, sessionId, "", "", "ENDED")
    }

    @TestConfiguration
    class Fakes {
        @Bean @Primary fun fakeAi() = FakeAi()
        @Bean @Primary fun fakeMedia() = FakeMedia()
    }

    @Autowired lateinit var facade: CardTrainingFacade
    @Autowired lateinit var voice: VoiceTrainingService
    @Autowired lateinit var fakeAi: FakeAi
    @Autowired lateinit var fakeMedia: FakeMedia
    @Autowired lateinit var mvc: MockMvc

    private fun sessionId() = facade.createSession(CreateCardSessionRequest(mode = SessionMode.VOICE)).id

    private fun event(id: UUID, callId: String, type: SessionEventType, eventId: UUID = UUID.randomUUID()) =
        SessionEvent.create(id, type, EventSource.MEDIA,
            mapOf("callId" to callId, "aiSessionId" to "voice-$id"), eventId)

    @Test
    fun `voice lifecycle, replay and late events keep terminal state`() {
        val id = sessionId()
        val call = voice.start(id, "PJSIP/1001")
        assertEquals("RINGING", call.state)
        assertEquals(SessionState.READY, facade.get(id).state)

        val ringing = event(id, call.callId, SessionEventType.CALL_RINGING)
        assertTrue(voice.receive(ringing))
        assertFalse(voice.receive(ringing))
        assertEquals(SessionState.RINGING, facade.get(id).state)

        assertTrue(voice.receive(event(id, call.callId, SessionEventType.CALL_ANSWERED)))
        assertEquals(SessionState.ACTIVE, facade.get(id).state)
        assertNotNull(facade.get(id).startedAt)
        assertEquals("ACTIVE", voice.getCall(id).state)
        assertTrue(voice.receive(event(id, call.callId, SessionEventType.TRANSCRIPT_FINAL)))

        assertEquals("ENDED", voice.hangup(id).state)
        assertEquals(SessionState.ACTIVE, facade.get(id).state) // callback owns business state
        val ended = event(id, call.callId, SessionEventType.CALL_ENDED)
        assertTrue(voice.receive(ended))
        assertFalse(voice.receive(ended))
        assertEquals(SessionState.COMPLETED, facade.get(id).state)
        assertNotNull(facade.get(id).endedAt)
        assertEquals("ENDED", voice.hangup(id).state)
        assertEquals(1, fakeAi.closed.count { it == call.aiSessionId })

        voice.receive(event(id, call.callId, SessionEventType.CALL_RINGING))
        voice.receive(event(id, call.callId, SessionEventType.MEDIA_ERROR))
        assertEquals(SessionState.COMPLETED, facade.get(id).state)
        assertEquals("ENDED", voice.getCall(id).state)
        assertEquals(1, voice.events(id).count { it.type == "session.started" })
        assertEquals(1, voice.events(id).count { it.type == "session.completed" })
    }

    @Test
    fun `foreign call and duplicate start are rejected`() {
        val id = sessionId()
        voice.start(id, "1001")
        assertThrows(IllegalStateException::class.java) { voice.start(id, "1001") }
        assertThrows(IllegalStateException::class.java) {
            voice.receive(event(id, "foreign", SessionEventType.CALL_ANSWERED))
        }
        assertEquals(SessionState.READY, facade.get(id).state)
    }

    @Test
    fun `Media failure can be retried without losing voice session or card demo`() {
        val id = sessionId()
        fakeMedia.failStart = true
        try {
            assertThrows(UpstreamUnavailableException::class.java) { voice.start(id, "1001") }
            assertEquals(SessionState.READY, facade.get(id).state)
        } finally {
            fakeMedia.failStart = false
        }
        assertEquals("RINGING", voice.start(id, "1001").state)
        val card = facade.createSession(CreateCardSessionRequest())
        assertEquals(SessionState.ACTIVE, facade.start(card.id).state)
        assertTrue(facade.assignments().none { it.session.id == id })
        assertThrows(IllegalStateException::class.java) { facade.stop(id) }
    }

    @Test
    fun `HTTP media event endpoint accepts envelope`() {
        val id = sessionId()
        val call = voice.start(id, "1001")
        mvc.perform(post("/internal/v1/media/events")
            .contentType(MediaType.APPLICATION_JSON)
            .content("""{"eventId":"${UUID.randomUUID()}","sessionId":"$id","type":"call.ringing","timestamp":"2026-09-21T12:00:00Z","source":"media","payload":{"callId":"${call.callId}","aiSessionId":"${call.aiSessionId}"}}"""))
            .andExpect(status().isOk)
        assertEquals(SessionState.RINGING, facade.get(id).state)
    }
}
