package ru.sirena112.core.card

import com.fasterxml.jackson.databind.JsonNode
import com.fasterxml.jackson.databind.ObjectMapper
import com.fasterxml.jackson.databind.node.ObjectNode
import org.hamcrest.Matchers.hasSize
import org.junit.jupiter.api.Test
import org.springframework.beans.factory.annotation.Autowired
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc
import org.springframework.boot.test.context.SpringBootTest
import org.springframework.http.MediaType
import org.springframework.test.web.servlet.MockMvc
import org.springframework.test.web.servlet.get
import org.springframework.test.web.servlet.patch
import org.springframework.test.web.servlet.post
import java.nio.file.Files
import java.nio.file.Paths

/**
 * Сквозной поток карточки по контракту 0.3: клиент отправляет только исходные
 * данные, тип происшествия и службы вычисляет Core по каталогу задачи #32.
 */
@SpringBootTest
@AutoConfigureMockMvc
class CardTrainingControllerTest {

    @Autowired
    lateinit var mockMvc: MockMvc

    @Autowired
    lateinit var objectMapper: ObjectMapper

    private fun expectedInput(): JsonNode =
        objectMapper.readTree(
            repoRoot().resolve(Paths.get("contracts", "examples", "scenario-1050602.json")).toFile()
        ).at("/groundTruth/expectedInput")

    private fun repoRoot(): java.nio.file.Path {
        var dir = Paths.get("").toAbsolutePath()
        repeat(8) {
            if (Files.isRegularFile(dir.resolve(Paths.get("contracts", "catalog", "classifier-v046-11.json")))) {
                return dir
            }
            dir = dir.parent ?: return@repeat
        }
        throw IllegalStateException("Корень репозитория с contracts/ не найден")
    }

    private fun startSession(): String {
        val created = mockMvc.post("/api/teacher/sessions")
            .andExpect { status { isCreated() } }
            .andReturn()
        val sessionId = objectMapper.readTree(created.response.contentAsString).get("id").asText()
        mockMvc.post("/api/teacher/sessions/$sessionId/start")
            .andExpect { status { isOk() } }
        return sessionId
    }

    private fun saveBody(input: JsonNode, expectedRevision: Int? = null): String {
        val body = objectMapper.createObjectNode()
        body.set<JsonNode>("input", input)
        expectedRevision?.let { body.put("expectedRevision", it) }
        return objectMapper.writeValueAsString(body)
    }

    @Test
    fun `teacher to student card flow computes classification by catalog`() {
        mockMvc.get("/api/teacher/scenarios")
            .andExpect {
                status { isOk() }
                jsonPath("$", hasSize<Any>(4))
                jsonPath("$[0].groundTruth.classifierVersion") { value("046-2024-11-15") }
                jsonPath("$[0].groundTruth.classifierCode") { value("1050602") }
                jsonPath("$[0].groundTruth.requiredServices", hasSize<Any>(14))
            }

        val created = mockMvc.post("/api/teacher/sessions") {
            contentType = MediaType.APPLICATION_JSON
            content = "{\"scenarioId\":\"${CardTrainingFacade.DEFAULT_SCENARIO_ID}\"}"
        }.andExpect {
            status { isCreated() }
            jsonPath("$.state") { value("CREATED") }
            jsonPath("$.mode") { value("CARD") }
            jsonPath("$.cardRevision") { value(0) }
        }.andReturn()
        val sessionId = objectMapper.readTree(created.response.contentAsString).get("id").asText()

        mockMvc.post("/api/teacher/sessions/$sessionId/start")
            .andExpect {
                status { isOk() }
                jsonPath("$.state") { value("ACTIVE") }
                jsonPath("$.startedAt") { exists() }
                jsonPath("$.timeLimitExceeded") { value(false) }
            }

        mockMvc.get("/api/student/assignments")
            .andExpect {
                status { isOk() }
                jsonPath("$[0].scenario.groundTruth.classifierCode") { value("1050602") }
                jsonPath("$[0].session.id") { value(sessionId) }
                jsonPath("$[0].session.state") { value("ACTIVE") }
            }

        mockMvc.get("/api/student/sessions/$sessionId/card-form")
            .andExpect {
                status { isOk() }
                jsonPath("$.classifierVersion") { value("046-2024-11-15") }
                jsonPath("$.signGroups", hasSize<Any>(3))
                jsonPath("$.signGroups[0].options[?(@.id == 'sign.68eaae1dc9472ce9')].label") { value("жилой дом") }
            }

        mockMvc.patch("/api/student/sessions/$sessionId/card") {
            contentType = MediaType.APPLICATION_JSON
            content = saveBody(expectedInput())
        }.andExpect {
            status { isOk() }
            jsonPath("$.card.calculation.status") { value("RESOLVED") }
            jsonPath("$.card.calculation.classifierCode") { value("1050602") }
            jsonPath("$.card.calculation.incidentType") { value("задымление: мусоропровод") }
            jsonPath("$.card.calculation.ekp35IncidentType") { value("пожар: мусоропровод") }
            jsonPath("$.card.calculation.responseScenarioCode") { value("1_9") }
            jsonPath("$.card.calculation.mainServices[0].id") { value("MCHS") }
            jsonPath("$.card.calculation.services", hasSize<Any>(14))
            jsonPath("$.card.calculation.missingInputIds", hasSize<Any>(0))
            jsonPath("$.cardRevision") { value(1) }
        }

        mockMvc.post("/api/teacher/sessions/$sessionId/stop")
            .andExpect {
                status { isOk() }
                jsonPath("$.state") { value("COMPLETED") }
            }

        mockMvc.post("/api/student/sessions/$sessionId/submit") {
            contentType = MediaType.APPLICATION_JSON
            content = saveBody(expectedInput())
        }.andExpect {
            status { isAccepted() }
            jsonPath("$.passed") { value(true) }
            jsonPath("$.score") { value(100.0) }
            jsonPath("$.errors", hasSize<Any>(0))
            jsonPath("$.classifierCode") { value("1050602") }
        }

        mockMvc.get("/api/teacher/sessions/$sessionId/report")
            .andExpect {
                status { isOk() }
                jsonPath("$.sessionId") { value(sessionId) }
                jsonPath("$.classifierCode") { value("1050602") }
                jsonPath("$.classifierVersion") { value("046-2024-11-15") }
                jsonPath("$.criteria", hasSize<Any>(4))
            }
    }

    @Test
    fun `draft can be saved before completion and submit rejects incomplete card`() {
        val sessionId = startSession()

        mockMvc.patch("/api/student/sessions/$sessionId/card") {
            contentType = MediaType.APPLICATION_JSON
            content = saveBody(
                objectMapper.readTree("""{"incident":{"selectedSignIds":["sign.68eaae1dc9472ce9"]}}""")
            )
        }.andExpect {
            status { isOk() }
            jsonPath("$.card.calculation.status") { value("INCOMPLETE") }
            jsonPath("$.card.calculation.classifierCode") { doesNotExist() }
            jsonPath("$.card.calculation.missingInputIds[0]") { value("signs.level2") }
            jsonPath("$.cardRevision") { value(1) }
        }

        val incomplete = expectedInput().deepCopy<ObjectNode>()
        incomplete.remove("victims")
        incomplete.remove("address")
        mockMvc.post("/api/student/sessions/$sessionId/submit") {
            contentType = MediaType.APPLICATION_JSON
            content = saveBody(incomplete)
        }.andExpect {
            status { isBadRequest() }
            jsonPath("$.message") {
                value("Не заполнены обязательные поля карточки: incident.address.displayAddress, victims.present")
            }
        }
    }

    @Test
    fun `client cannot substitute computed fields`() {
        val sessionId = startSession()

        val tamperedType = expectedInput().deepCopy<ObjectNode>()
        tamperedType.put("incidentType", "подменённый тип")
        mockMvc.patch("/api/student/sessions/$sessionId/card") {
            contentType = MediaType.APPLICATION_JSON
            content = saveBody(tamperedType)
        }.andExpect {
            status { isBadRequest() }
            jsonPath("$.code") { value("BAD_REQUEST") }
        }

        val tamperedServices = expectedInput().deepCopy<ObjectNode>()
        tamperedServices.putArray("requiredServices").add("POLICE")
        mockMvc.post("/api/student/sessions/$sessionId/submit") {
            contentType = MediaType.APPLICATION_JSON
            content = saveBody(tamperedServices)
        }.andExpect {
            status { isBadRequest() }
            jsonPath("$.code") { value("BAD_REQUEST") }
        }

        mockMvc.get("/api/student/sessions/$sessionId")
            .andExpect {
                status { isOk() }
                jsonPath("$.cardRevision") { value(0) }
            }
    }

    @Test
    fun `conditional ambulance changes routing and fails mismatching criteria`() {
        val sessionId = startSession()

        val withVictims = objectMapper.createObjectNode().apply {
            set<ObjectNode>("incident", objectMapper.createObjectNode().apply {
                putArray("selectedSignIds").apply {
                    add("sign.68eaae1dc9472ce9")
                    add("sign.8795ab4a7bb0d66a")
                    add("sign.8b0cf230ebb8ba99")
                }
                putArray("answers").apply {
                    expectedInput().at("/incident/answers").forEach { answer ->
                        add(objectMapper.createObjectNode().apply {
                            put("questionId", answer.get("questionId").asText())
                            putArray("optionIds").add(
                                if (answer.get("questionId").asText() == "routing.victims-status") "PRESENT"
                                else answer.get("optionIds")[0].asText()
                            )
                        })
                    }
                }
            })
            set<ObjectNode>("address", objectMapper.createObjectNode().put("displayAddress", "Учебный адрес, дом 1"))
            set<ObjectNode>("victims", objectMapper.createObjectNode().put("present", true))
        }

        mockMvc.patch("/api/student/sessions/$sessionId/card") {
            contentType = MediaType.APPLICATION_JSON
            content = saveBody(withVictims)
        }.andExpect {
            status { isOk() }
            jsonPath("$.card.calculation.status") { value("RESOLVED") }
            jsonPath("$.card.calculation.services[?(@.id == 'AMBULANCE')]", hasSize<Any>(1))
        }

        mockMvc.post("/api/student/sessions/$sessionId/submit") {
            contentType = MediaType.APPLICATION_JSON
            content = saveBody(withVictims)
        }.andExpect {
            status { isAccepted() }
            jsonPath("$.passed") { value(false) }
            jsonPath("$.errors", hasSize<Any>(2))
        }
    }

    @Test
    fun `stale draft revision is rejected`() {
        val sessionId = startSession()

        mockMvc.patch("/api/student/sessions/$sessionId/card") {
            contentType = MediaType.APPLICATION_JSON
            content = saveBody(expectedInput(), expectedRevision = 0)
        }.andExpect { status { isOk() } }

        mockMvc.patch("/api/student/sessions/$sessionId/card") {
            contentType = MediaType.APPLICATION_JSON
            content = saveBody(expectedInput(), expectedRevision = 0)
        }.andExpect {
            status { isConflict() }
            jsonPath("$.message") { value("Устаревшая ревизия карточки сессии $sessionId: ожидается 1, получено 0") }
        }
    }

    @Test
    fun `empty card is rejected and does not advance the session`() {
        val sessionId = startSession()

        mockMvc.patch("/api/student/sessions/$sessionId/card") {
            contentType = MediaType.APPLICATION_JSON
            content = "{\"input\":{}}"
        }.andExpect {
            status { isBadRequest() }
            jsonPath("$.code") { value("BAD_REQUEST") }
        }

        mockMvc.get("/api/student/sessions/$sessionId")
            .andExpect {
                status { isOk() }
                jsonPath("$.state") { value("ACTIVE") }
                jsonPath("$.cardRevision") { value(0) }
            }
    }
}
