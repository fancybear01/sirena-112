package ru.sirena112.core.events

import com.fasterxml.jackson.databind.ObjectMapper
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Test
import org.mockito.ArgumentMatchers.any
import org.mockito.Mockito.*
import org.springframework.web.socket.CloseStatus
import org.springframework.web.socket.TextMessage
import org.springframework.web.socket.WebSocketSession
import ru.sirena112.core.domain.*
import java.net.URI
import java.util.UUID

class SessionEventReplayTest {
    @Test
    fun `known cursor replays only later events`() {
        val sessionId = UUID.randomUUID()
        val repository = mock(SessionEventRepository::class.java)
        val socket = mock(WebSocketSession::class.java)
        val mapper = ObjectMapper().findAndRegisterModules()
        val before = SessionEvent.create(sessionId, SessionEventType.SESSION_CREATED, EventSource.CORE)
        val cursor = SessionEvent.create(sessionId, SessionEventType.SESSION_STARTED, EventSource.CORE)
        val after = SessionEvent.create(sessionId, SessionEventType.OPERATOR_CARD_UPDATED, EventSource.CORE)
        `when`(socket.id).thenReturn("cursor-connection")
        `when`(socket.uri).thenReturn(URI(
            "ws://localhost/ws/sessions/$sessionId/events?afterEventId=${cursor.eventId}"
        ))
        `when`(socket.isOpen).thenReturn(true)
        `when`(repository.findBySessionId(sessionId)).thenReturn(listOf(before, cursor, after))
        val subscriptions = object : SessionEventSubscription {
            override fun subscribe(id: UUID, callback: (SessionEvent) -> Unit): () -> Unit = {}
        }
        val received = mutableListOf<String>()
        doAnswer { invocation ->
            received += mapper.readTree(invocation.getArgument<TextMessage>(0).payload)["eventId"].asText()
            null
        }.`when`(socket).sendMessage(any())

        SessionEventWebSocketHandler(repository, subscriptions, mapper).afterConnectionEstablished(socket)

        assertEquals(listOf(after.eventId.toString()), received)
    }

    @Test
    fun `unknown cursor falls back to full replay`() {
        val sessionId = UUID.randomUUID()
        val repository = mock(SessionEventRepository::class.java)
        val socket = mock(WebSocketSession::class.java)
        val mapper = ObjectMapper().findAndRegisterModules()
        val history = listOf(
            SessionEvent.create(sessionId, SessionEventType.SESSION_CREATED, EventSource.CORE),
            SessionEvent.create(sessionId, SessionEventType.SESSION_STARTED, EventSource.CORE)
        )
        `when`(socket.id).thenReturn("stale-cursor-connection")
        `when`(socket.uri).thenReturn(URI(
            "ws://localhost/ws/sessions/$sessionId/events?afterEventId=${UUID.randomUUID()}"
        ))
        `when`(socket.isOpen).thenReturn(true)
        `when`(repository.findBySessionId(sessionId)).thenReturn(history)
        val subscriptions = object : SessionEventSubscription {
            override fun subscribe(id: UUID, callback: (SessionEvent) -> Unit): () -> Unit = {}
        }
        val received = mutableListOf<String>()
        doAnswer { invocation ->
            received += mapper.readTree(invocation.getArgument<TextMessage>(0).payload)["eventId"].asText()
            null
        }.`when`(socket).sendMessage(any())

        SessionEventWebSocketHandler(repository, subscriptions, mapper).afterConnectionEstablished(socket)

        assertEquals(history.map { it.eventId.toString() }, received)
    }

    @Test
    fun `live events during snapshot are ordered after replay without duplicates`() {
        val sessionId = UUID.randomUUID()
        val repository = mock(SessionEventRepository::class.java)
        val socket = mock(WebSocketSession::class.java)
        val mapper = ObjectMapper().findAndRegisterModules()
        `when`(socket.id).thenReturn("connection")
        `when`(socket.uri).thenReturn(URI("ws://localhost/ws/sessions/$sessionId/events"))
        `when`(socket.isOpen).thenReturn(true)
        val history = SessionEvent.create(sessionId, SessionEventType.SESSION_CREATED, EventSource.CORE)
        val overlap = SessionEvent.create(sessionId, SessionEventType.SERVICE_ASSIGNED, EventSource.CORE)
        val afterSnapshot = SessionEvent.create(sessionId, SessionEventType.SERVICE_STATUS_CHANGED, EventSource.CORE)
        var listener: ((SessionEvent) -> Unit)? = null
        var unsubscribed = false
        val subscriptions = object : SessionEventSubscription {
            override fun subscribe(id: UUID, callback: (SessionEvent) -> Unit): () -> Unit {
                assertEquals(sessionId, id)
                listener = callback
                return { unsubscribed = true }
            }
        }
        `when`(repository.findBySessionId(sessionId)).thenAnswer {
            listener!!(overlap)
            listener!!(afterSnapshot)
            listOf(history, overlap)
        }
        val received = mutableListOf<String>()
        doAnswer { invocation ->
            received += mapper.readTree(invocation.getArgument<TextMessage>(0).payload)["eventId"].asText()
            null
        }.`when`(socket).sendMessage(any())
        val handler = SessionEventWebSocketHandler(repository, subscriptions, mapper)
        handler.afterConnectionEstablished(socket)
        val live = SessionEvent.create(sessionId, SessionEventType.SERVICE_STATUS_CHANGED, EventSource.CORE)
        listener!!(live)
        assertEquals(listOf(history, overlap, afterSnapshot, live).map { it.eventId.toString() }, received)
        handler.afterConnectionClosed(socket, CloseStatus.NORMAL)
        assertEquals(true, unsubscribed)
    }
}
