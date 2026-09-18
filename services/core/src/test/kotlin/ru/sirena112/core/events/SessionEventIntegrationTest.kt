package ru.sirena112.core.events

import com.fasterxml.jackson.databind.ObjectMapper
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import org.springframework.beans.factory.annotation.Autowired
import org.springframework.boot.test.context.SpringBootTest
import ru.sirena112.core.card.CardTrainingFacade
import ru.sirena112.core.card.CreateCardSessionRequest
import ru.sirena112.core.card.SaveCardRequest
import ru.sirena112.core.card.SubmitCardRequest
import ru.sirena112.core.classifier.ContractTestSupport
import ru.sirena112.core.classifier.OperatorCardInput
import ru.sirena112.core.domain.InMemorySessionEventRepository
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
        val input = ContractTestSupport.objectMapper.convertValue(
            ContractTestSupport.fixtureNode("scenario-1050602.json").at("/groundTruth/expectedInput"),
            OperatorCardInput::class.java
        )
        val session = facade.createSession(CreateCardSessionRequest())
        val received = CopyOnWriteArrayList<String>()
        val unsubscribe = events.subscribe(session.id) { received += it.type }

        facade.start(session.id)
        facade.saveCard(session.id, SaveCardRequest(input))
        facade.submit(session.id, SubmitCardRequest(input))
        unsubscribe()

        val persisted = events.findBySessionId(session.id)
        val types = persisted.map { it.type }
        assertEquals(
            listOf(
                "session.created",
                "session.started",
                "card.answers_updated",
                "routing.calculated",
                "operator.card_updated",
                "operator.answer_submitted",
                "session.completed",
                "score.started",
                "score.completed"
            ),
            types
        )
        assertEquals(types.drop(1), received)

        val answersEvent = persisted.first { it.type == "card.answers_updated" }
        assertEquals(1, answersEvent.payload["cardRevision"])
        assertEquals(3, (answersEvent.payload["selectedSignIds"] as List<*>).size)

        val routing = persisted.first { it.type == "routing.calculated" }
        assertEquals(1, routing.payload["cardRevision"])
        assertEquals("RESOLVED", routing.payload["status"])
        assertEquals("1050602", routing.payload["classifierCode"])
        assertEquals("046-2024-11-15", routing.payload["classifierVersion"])
        assertEquals(14, (routing.payload["serviceIds"] as List<*>).size)
        assertTrue((routing.payload["missingInputIds"] as List<*>).isEmpty())
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
