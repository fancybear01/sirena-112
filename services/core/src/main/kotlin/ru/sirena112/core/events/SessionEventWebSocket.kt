package ru.sirena112.core.events

import com.fasterxml.jackson.databind.ObjectMapper
import org.springframework.context.annotation.Configuration
import org.springframework.web.socket.CloseStatus
import org.springframework.web.socket.TextMessage
import org.springframework.web.socket.WebSocketHandler
import org.springframework.web.socket.WebSocketSession
import org.springframework.web.socket.config.annotation.EnableWebSocket
import org.springframework.web.socket.config.annotation.WebSocketConfigurer
import org.springframework.web.socket.config.annotation.WebSocketHandlerRegistry
import org.springframework.web.socket.handler.TextWebSocketHandler
import ru.sirena112.core.domain.SessionEvent
import ru.sirena112.core.domain.SessionEventRepository
import ru.sirena112.core.domain.SessionEventSubscription
import java.util.UUID
import java.util.concurrent.ConcurrentHashMap

/** Отдаёт события одной учебной сессии в реальном времени без брокера. */
class SessionEventWebSocketHandler(
    private val events: SessionEventRepository,
    private val subscriptions: SessionEventSubscription,
    private val objectMapper: ObjectMapper
) : TextWebSocketHandler() {
    private val connectionSubscriptions = ConcurrentHashMap<String, () -> Unit>()

    override fun afterConnectionEstablished(session: WebSocketSession) {
        val sessionId = sessionId(session) ?: run {
            session.close(CloseStatus.BAD_DATA)
            return
        }
        // Subscribe before reading history so no event can fall into the gap.
        // Buffer live events until replay finishes; both paths share one send lock.
        // Never hold this lock while reading the repository (publish holds its own lock).
        val sendLock = Any()
        val pending = mutableListOf<SessionEvent>()
        var replaying = true
        val listener: (SessionEvent) -> Unit = { event ->
            synchronized(sendLock) {
                if (replaying) pending += event else send(session, event)
            }
        }
        val unsubscribe = subscriptions.subscribe(sessionId, listener)
        connectionSubscriptions[session.id] = unsubscribe

        try {
            val history = events.findBySessionId(sessionId)
            synchronized(sendLock) {
                history.forEach { send(session, it) }
                val replayedIds = history.mapTo(mutableSetOf()) { it.eventId }
                pending.filterNot { it.eventId in replayedIds }.forEach { send(session, it) }
                pending.clear()
                replaying = false
            }
        } catch (exception: Exception) {
            handleTransportError(session, exception)
        }
        if (!session.isOpen) connectionSubscriptions.remove(session.id)?.invoke()
    }

    override fun afterConnectionClosed(session: WebSocketSession, closeStatus: CloseStatus) {
        connectionSubscriptions.remove(session.id)?.invoke()
    }

    override fun handleTransportError(session: WebSocketSession, exception: Throwable) {
        connectionSubscriptions.remove(session.id)?.invoke()
        if (session.isOpen) runCatching { session.close(CloseStatus.SERVER_ERROR) }
    }

    private fun send(session: WebSocketSession, event: SessionEvent) {
        if (!session.isOpen) return
        runCatching {
            session.sendMessage(TextMessage(objectMapper.writeValueAsString(event)))
        }.onFailure {
            connectionSubscriptions.remove(session.id)?.invoke()
            runCatching { session.close(CloseStatus.SERVER_ERROR) }
        }
    }

    private fun sessionId(session: WebSocketSession): UUID? = session.uri?.path
        ?.removePrefix("/ws/sessions/")
        ?.removeSuffix("/events")
        ?.takeIf { it.isNotBlank() }
        ?.let { runCatching { UUID.fromString(it) }.getOrNull() }
}

@Configuration
@EnableWebSocket
class SessionEventWebSocketConfiguration(
    private val events: SessionEventRepository,
    private val subscriptions: SessionEventSubscription,
    private val objectMapper: ObjectMapper
) : WebSocketConfigurer {
    override fun registerWebSocketHandlers(registry: WebSocketHandlerRegistry) {
        registry.addHandler(SessionEventWebSocketHandler(events, subscriptions, objectMapper), "/ws/sessions/{sessionId}/events")
            .setAllowedOrigins("*")
    }
}
