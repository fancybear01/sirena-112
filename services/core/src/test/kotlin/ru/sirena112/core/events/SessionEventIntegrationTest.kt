package ru.sirena112.core.events

import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import org.springframework.beans.factory.annotation.Autowired
import org.springframework.boot.test.context.SpringBootTest
import ru.sirena112.core.card.CardTrainingFacade
import ru.sirena112.core.card.CreateCardSessionRequest
import ru.sirena112.core.card.SaveCardRequest
import ru.sirena112.core.domain.InMemorySessionEventRepository
import ru.sirena112.core.domain.IncidentSigns
import java.util.UUID
import java.util.concurrent.CopyOnWriteArrayList

@SpringBootTest
class SessionEventIntegrationTest {
    @Autowired
    lateinit var facade: CardTrainingFacade

    @Autowired
    lateinit var events: InMemorySessionEventRepository

    @Test
    fun `card flow persists contract events and notifies subscribers`() {
        val session = facade.createSession(CreateCardSessionRequest())
        val received = CopyOnWriteArrayList<String>()
        val unsubscribe = events.subscribe(session.id) { received += it.type }

        facade.start(session.id)
        facade.saveCard(
            session.id,
            SaveCardRequest(
                incidentType = "задымление: мусоропровод",
                signs = IncidentSigns("жилой дом", "мусоропровод", "дым"),
                address = "Москва, ул. Берзарина, д. 21, корп. 1, под. 3",
                requiredServices = setOf("Служба 101", "ДДС района", "МОЭК")
            )
        )
        facade.submit(session.id)
        unsubscribe()

        val types = events.findBySessionId(session.id).map { it.type }
        assertEquals(
            listOf(
                "session.created", "session.started", "operator.card_updated",
                "operator.answer_submitted", "session.completed", "score.started", "score.completed"
            ),
            types
        )
        assertEquals(types.drop(1), received)
        assertTrue(types.all { it.isNotBlank() })
    }

    @Test
    fun `mock clients do not require external services`() {
        val sessionId = UUID.randomUUID()
        val scenarioId = UUID.randomUUID()
        val ai = ru.sirena112.core.integration.MockAiClient()
        val media = ru.sirena112.core.integration.MockMediaClient()
        val aiSession = ai.createSession(sessionId, scenarioId)
        val call = media.startCall(
            ru.sirena112.core.integration.MediaCallCommand(sessionId, aiSession.aiSessionId, "sip:test")
        )

        assertTrue(aiSession.aiSessionId.startsWith("mock-ai-"))
        assertTrue(call.started)
        assertEquals(false, media.hangup(sessionId).started)
    }
}
