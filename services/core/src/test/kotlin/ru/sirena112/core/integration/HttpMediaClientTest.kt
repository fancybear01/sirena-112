package ru.sirena112.core.integration

import com.fasterxml.jackson.databind.ObjectMapper
import com.fasterxml.jackson.module.kotlin.registerKotlinModule
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertThrows
import org.junit.jupiter.api.Test
import org.springframework.http.HttpMethod
import org.springframework.http.MediaType
import org.springframework.http.converter.json.MappingJackson2HttpMessageConverter
import org.springframework.test.web.client.MockRestServiceServer
import org.springframework.test.web.client.match.MockRestRequestMatchers.method
import org.springframework.test.web.client.match.MockRestRequestMatchers.requestTo
import org.springframework.test.web.client.response.MockRestResponseCreators.withStatus
import org.springframework.test.web.client.response.MockRestResponseCreators.withSuccess
import org.springframework.http.HttpStatus
import org.springframework.web.client.RestTemplate
import ru.sirena112.core.config.CoreProperties
import java.util.UUID

class HttpMediaClientTest {
    private val template = RestTemplate().apply {
        messageConverters.add(MappingJackson2HttpMessageConverter(ObjectMapper().registerKotlinModule()))
    }
    private val server = MockRestServiceServer.createServer(template)
    private val client = HttpMediaClient(template, CoreProperties(mediaBaseUrl = "http://media.test"))

    @Test
    fun `start and hangup respect Media HTTP contract`() {
        val id = UUID.randomUUID()
        server.expect(requestTo("http://media.test/internal/v1/calls/start"))
            .andExpect(method(HttpMethod.POST))
            .andRespond(withStatus(HttpStatus.ACCEPTED).contentType(MediaType.APPLICATION_JSON)
                .body("""{"callId":"call-1","sessionId":"$id","aiSessionId":"voice-1","sipAddress":"1001","state":"RINGING"}"""))
        server.expect(requestTo("http://media.test/internal/v1/calls/hangup"))
            .andExpect(method(HttpMethod.POST))
            .andRespond(withSuccess("""{"callId":"call-1","sessionId":"$id","state":"ENDED"}""",
                MediaType.APPLICATION_JSON))
        assertEquals("call-1", client.startCall(MediaCallCommand(id, "voice-1", "1001")).callId)
        assertEquals("ENDED", client.hangup("call-1", id).state)
        server.verify()
    }

    @Test
    fun `conflict and unavailable are explicit`() {
        val id = UUID.randomUUID()
        server.expect(requestTo("http://media.test/internal/v1/calls/start"))
            .andRespond(withStatus(HttpStatus.CONFLICT))
        server.expect(requestTo("http://media.test/internal/v1/calls/start"))
            .andRespond(withStatus(HttpStatus.SERVICE_UNAVAILABLE))
        assertThrows(UpstreamConflictException::class.java) {
            client.startCall(MediaCallCommand(id, "voice-1", "1001"))
        }
        assertThrows(UpstreamUnavailableException::class.java) {
            client.startCall(MediaCallCommand(id, "voice-1", "1001"))
        }
    }

    @Test
    fun `wrong session in response is rejected`() {
        server.expect(requestTo("http://media.test/internal/v1/calls/start"))
            .andRespond(withStatus(HttpStatus.ACCEPTED).contentType(MediaType.APPLICATION_JSON)
                .body("""{"callId":"call-1","sessionId":"${UUID.randomUUID()}","aiSessionId":"voice-1","sipAddress":"1001","state":"RINGING"}"""))
        assertThrows(UpstreamProtocolException::class.java) {
            client.startCall(MediaCallCommand(UUID.randomUUID(), "voice-1", "1001"))
        }
    }
}
