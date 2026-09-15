package ru.sirena112.core.card

import com.fasterxml.jackson.databind.ObjectMapper
import org.hamcrest.Matchers.hasSize
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Test
import org.springframework.beans.factory.annotation.Autowired
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc
import org.springframework.boot.test.context.SpringBootTest
import org.springframework.http.MediaType
import org.springframework.test.web.servlet.MockMvc
import org.springframework.test.web.servlet.get
import org.springframework.test.web.servlet.patch
import org.springframework.test.web.servlet.post

@SpringBootTest
@AutoConfigureMockMvc
class CardTrainingControllerTest {

    @Autowired
    lateinit var mockMvc: MockMvc

    @Autowired
    lateinit var objectMapper: ObjectMapper

    @Test
    fun `teacher to student card flow produces a mock report`() {
        mockMvc.get("/api/teacher/scenarios")
            .andExpect {
                status { isOk() }
                jsonPath("$", hasSize<Any>(1))
                jsonPath("$[0].groundTruth.ekpCode") { value("1050602") }
                jsonPath("$[0].groundTruth.signs.level1") { value("жилой дом") }
            }

        val created = mockMvc.post("/api/teacher/sessions") {
            contentType = MediaType.APPLICATION_JSON
            content = "{\"scenarioId\":\"${CardTrainingFacade.FIXED_SCENARIO_ID}\"}"
        }.andExpect {
            status { isCreated() }
            jsonPath("$.state") { value("CREATED") }
            jsonPath("$.mode") { value("CARD") }
        }.andReturn()
        val sessionId = objectMapper.readTree(created.response.contentAsString).get("id").asText()

        mockMvc.post("/api/teacher/sessions/$sessionId/start")
            .andExpect {
                status { isOk() }
                jsonPath("$.state") { value("ACTIVE") }
            }

        mockMvc.patch("/api/student/sessions/$sessionId/card") {
            contentType = MediaType.APPLICATION_JSON
            content = """
                {
                  "incidentType": "задымление: мусоропровод",
                  "signs": {"level1":"жилой дом", "level2":"мусоропровод", "level3":"дым"},
                  "address": "Москва, ул. Берзарина, д. 21, корп. 1, под. 3",
                  "requiredServices": ["Служба 101", "ДДС района", "МОЭК"]
                }
            """.trimIndent()
        }.andExpect {
            status { isOk() }
            jsonPath("$.card.incidentType") { value("задымление: мусоропровод") }
        }

        mockMvc.post("/api/teacher/sessions/$sessionId/stop")
            .andExpect {
                status { isOk() }
                jsonPath("$.state") { value("COMPLETED") }
            }

        mockMvc.post("/api/student/sessions/$sessionId/submit")
            .andExpect {
                status { isAccepted() }
                jsonPath("$.passed") { value(true) }
                jsonPath("$.score") { value(100.0) }
                jsonPath("$.errors", hasSize<Any>(0))
            }

        mockMvc.get("/api/teacher/sessions/$sessionId/report")
            .andExpect {
                status { isOk() }
                jsonPath("$.sessionId") { value(sessionId) }
                jsonPath("$.criteria", hasSize<Any>(4))
            }
    }

    @Test
    fun `empty card is rejected and does not advance the session`() {
        val created = mockMvc.post("/api/teacher/sessions")
            .andExpect { status { isCreated() } }
            .andReturn()
        val sessionId = objectMapper.readTree(created.response.contentAsString).get("id").asText()
        mockMvc.post("/api/teacher/sessions/$sessionId/start")
            .andExpect { status { isOk() } }

        mockMvc.patch("/api/student/sessions/$sessionId/card") {
            contentType = MediaType.APPLICATION_JSON
            content = "{}"
        }.andExpect {
            status { isBadRequest() }
            jsonPath("$.code") { value("BAD_REQUEST") }
        }

        mockMvc.get("/api/student/sessions/$sessionId")
            .andExpect { jsonPath("$.state") { value("ACTIVE") } }
    }

    @Test
    fun `submit reports missing mandatory fields`() {
        val created = mockMvc.post("/api/teacher/sessions")
            .andExpect { status { isCreated() } }
            .andReturn()
        val sessionId = objectMapper.readTree(created.response.contentAsString).get("id").asText()
        mockMvc.post("/api/teacher/sessions/$sessionId/start")
            .andExpect { status { isOk() } }
        mockMvc.patch("/api/student/sessions/$sessionId/card") {
            contentType = MediaType.APPLICATION_JSON
            content = "{\"incidentType\":\"задымление: мусоропровод\"}"
        }.andExpect { status { isOk() } }

        mockMvc.post("/api/student/sessions/$sessionId/submit")
            .andExpect {
                status { isBadRequest() }
                jsonPath("$.message") { value("Не заполнены обязательные поля карточки: address, requiredServices") }
            }
    }
}
