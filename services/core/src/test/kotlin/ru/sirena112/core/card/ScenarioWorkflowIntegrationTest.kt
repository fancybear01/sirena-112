package ru.sirena112.core.card

import com.fasterxml.jackson.databind.ObjectMapper
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Test
import org.springframework.beans.factory.annotation.Autowired
import org.springframework.beans.factory.annotation.Qualifier
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc
import org.springframework.boot.test.context.SpringBootTest
import org.springframework.http.MediaType
import org.springframework.mock.web.MockHttpSession
import org.springframework.security.crypto.password.PasswordEncoder
import org.springframework.security.test.web.servlet.request.SecurityMockMvcRequestPostProcessors.csrf
import org.springframework.test.web.servlet.MockMvc
import org.springframework.test.web.client.MockRestServiceServer
import org.springframework.test.web.client.match.MockRestRequestMatchers.requestTo
import org.springframework.test.web.client.response.MockRestResponseCreators.withSuccess
import org.springframework.web.client.RestTemplate
import org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get
import org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post
import org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put
import ru.sirena112.core.auth.AccountRepository
import ru.sirena112.core.auth.AuthAccount
import ru.sirena112.core.auth.GroupRepository
import ru.sirena112.core.auth.LoginRequest
import ru.sirena112.core.auth.Role
import ru.sirena112.core.auth.TrainingGroup
import ru.sirena112.core.domain.ScenarioRepository
import ru.sirena112.core.domain.TrainingSessionService
import ru.sirena112.core.domain.SessionMode
import ru.sirena112.core.domain.OperatorCard
import ru.sirena112.core.classifier.ClassifierService
import ru.sirena112.core.classifier.CallerInput
import ru.sirena112.core.classifier.PhoneNumberInput
import ru.sirena112.core.classifier.AddressInput
import java.util.UUID

@SpringBootTest(properties = [
    "core.auth.enabled=true", "core.auth.bootstrap-admin-username=admin",
    "core.auth.bootstrap-admin-password=admin-password-for-tests",
    "core.auth.media-token=0123456789abcdef0123456789abcdef"
])
@AutoConfigureMockMvc
class ScenarioWorkflowIntegrationTest {
    @Autowired lateinit var mvc: MockMvc
    @Autowired lateinit var mapper: ObjectMapper
    @Autowired lateinit var scenarios: ScenarioRepository
    @Autowired lateinit var accounts: AccountRepository
    @Autowired lateinit var groups: GroupRepository
    @Autowired lateinit var encoder: PasswordEncoder
    @Autowired lateinit var sessionService: TrainingSessionService
    @Autowired lateinit var classifier: ClassifierService
    @Autowired @Qualifier("aiRestTemplate") lateinit var aiHttp: RestTemplate

    private fun login(username: String): MockHttpSession {
        val result = mvc.perform(post("/api/auth/login").with(csrf()).contentType(MediaType.APPLICATION_JSON)
            .content(mapper.writeValueAsString(LoginRequest(username, "teacher-password-123")))).andReturn()
        assertEquals(200, result.response.status, result.response.contentAsString)
        return result.request.session as MockHttpSession
    }

    @Test fun `draft is validated approved immutable and assigned only within teacher group`() {
        val firstGroup = TrainingGroup(UUID.randomUUID(), "first-${UUID.randomUUID()}")
        val secondGroup = TrainingGroup(UUID.randomUUID(), "second-${UUID.randomUUID()}")
        groups.insert(firstGroup); groups.insert(secondGroup)
        fun account(role: Role, group: TrainingGroup): AuthAccount = AuthAccount(UUID.randomUUID(),
            "u${UUID.randomUUID().toString().replace("-", "").take(12)}", encoder.encode("teacher-password-123"),
            role, "Test", group.id).also(accounts::insert)
        val teacher = account(Role.TEACHER, firstGroup)
        val foreignTeacher = account(Role.TEACHER, secondGroup)
        val student = account(Role.STUDENT, firstGroup)
        val foreign = account(Role.STUDENT, secondGroup)
        val teacherSession = login(teacher.username)
        val foreignTeacherSession = login(foreignTeacher.username)
        val studentSession = login(student.username)
        val foreignSession = login(foreign.username)
        val template = scenarios.findAll().first()
        val aiServer = MockRestServiceServer.createServer(aiHttp)
        aiServer.expect(requestTo("http://localhost:8090/ai/scenarios/generate"))
            .andRespond(withSuccess(mapper.writeValueAsString(mapOf("scenarios" to listOf(template))), MediaType.APPLICATION_JSON))
        val generated = mvc.perform(post("/api/teacher/scenarios/workflow/drafts/generate").session(teacherSession).with(csrf())
            .contentType(MediaType.APPLICATION_JSON).content("{\"category\":\"${template.category}\",\"difficulty\":\"${template.difficulty}\"}"))
            .andReturn()
        assertEquals(201, generated.response.status, generated.response.contentAsString)
        assertEquals("AI", mapper.readTree(generated.response.contentAsString)["source"].asText())
        aiServer.verify()
        val invalid = template.copy(groundTruth = template.groundTruth.copy(classifierCode = "999999"))
        val draft = mvc.perform(post("/api/teacher/scenarios/workflow/drafts").session(teacherSession).with(csrf())
            .contentType(MediaType.APPLICATION_JSON).content(mapper.writeValueAsString(DraftRequest(invalid, "Check truth"))))
            .andReturn()
        assertEquals(201, draft.response.status, draft.response.contentAsString)
        val created = mapper.readTree(draft.response.contentAsString)
        val id = created["id"].asText()
        assertEquals("DRAFT", created["status"].asText())
        assertEquals(400, mvc.perform(post("/api/teacher/scenarios/workflow/$id/approve?expectedRevision=0")
            .session(teacherSession).with(csrf())).andReturn().response.status)
        assertEquals(409, mvc.perform(post("/api/teacher/scenarios/workflow/$id/assign").session(teacherSession).with(csrf())
            .contentType(MediaType.APPLICATION_JSON).content("{\"studentId\":\"${student.id}\"}"))
            .andReturn().response.status)
        val updated = mvc.perform(put("/api/teacher/scenarios/workflow/$id").session(teacherSession).with(csrf())
            .contentType(MediaType.APPLICATION_JSON).content(mapper.writeValueAsString(DraftRequest(template, "Corrected", 0))))
            .andReturn()
        assertEquals(200, updated.response.status, updated.response.contentAsString)
        assertEquals(1, mapper.readTree(updated.response.contentAsString)["revision"].asInt())
        val approved = mvc.perform(post("/api/teacher/scenarios/workflow/$id/approve?expectedRevision=1")
            .session(teacherSession).with(csrf())).andReturn()
        assertEquals(200, approved.response.status, approved.response.contentAsString)
        assertEquals(false, mvc.perform(get("/api/teacher/scenarios").session(foreignTeacherSession))
            .andReturn().response.contentAsString.contains(id))
        assertEquals(403, mvc.perform(post("/api/teacher/sessions").session(foreignTeacherSession).with(csrf())
            .contentType(MediaType.APPLICATION_JSON).content("{\"scenarioId\":\"$id\",\"studentId\":\"${foreign.id}\"}"))
            .andReturn().response.status)
        val fork = mvc.perform(post("/api/teacher/scenarios/workflow/$id/fork").session(teacherSession).with(csrf()))
            .andReturn()
        assertEquals(201, fork.response.status, fork.response.contentAsString)
        assertEquals(2, mapper.readTree(fork.response.contentAsString)["version"].asInt())
        assertEquals(409, mvc.perform(put("/api/teacher/scenarios/workflow/$id").session(teacherSession).with(csrf())
            .contentType(MediaType.APPLICATION_JSON).content(mapper.writeValueAsString(DraftRequest(template, "tamper", 2))))
            .andReturn().response.status)
        assertEquals(403, mvc.perform(post("/api/teacher/scenarios/workflow/$id/assign").session(teacherSession).with(csrf())
            .contentType(MediaType.APPLICATION_JSON).content("{\"studentId\":\"${foreign.id}\"}"))
            .andReturn().response.status)
        val assigned = mvc.perform(post("/api/teacher/scenarios/workflow/$id/assign").session(teacherSession).with(csrf())
            .contentType(MediaType.APPLICATION_JSON).content("{\"studentId\":\"${student.id}\"}"))
            .andReturn()
        assertEquals(201, assigned.response.status, assigned.response.contentAsString)
        assertEquals("ACTIVE", mapper.readTree(assigned.response.contentAsString)[0]["state"].asText())
        assertEquals(true, mvc.perform(get("/api/student/assignments").session(studentSession)).andReturn()
            .response.contentAsString.contains(id))
        assertEquals(false, mvc.perform(get("/api/student/assignments").session(foreignSession)).andReturn()
            .response.contentAsString.contains(id))
        assertEquals(403, mvc.perform(get("/api/teacher/scenarios/workflow/$id").session(foreignSession))
            .andReturn().response.status)
    }

    @Test fun `student proposes sanitized scored card once for teacher approval`() {
        val group = TrainingGroup(UUID.randomUUID(), "student-proposals-${UUID.randomUUID()}")
        groups.insert(group)
        val student = AuthAccount(UUID.randomUUID(), "s${UUID.randomUUID().toString().replace("-", "").take(12)}",
            encoder.encode("teacher-password-123"), Role.STUDENT, "Student", group.id)
        accounts.insert(student)
        val teacher = AuthAccount(UUID.randomUUID(), "t${UUID.randomUUID().toString().replace("-", "").take(12)}",
            encoder.encode("teacher-password-123"), Role.TEACHER, "Teacher", group.id)
        accounts.insert(teacher)
        val studentSession = login(student.username)
        val teacherSession = login(teacher.username)
        val scenario = scenarios.findAll().first()
        val original = scenario.groundTruth.expectedInput
        val input = original.copy(caller = CallerInput(fullName = "PRIVATE_NAME",
            phoneNumbers = listOf(PhoneNumberInput("PRIVATE_PHONE", "PROVIDED"))),
            address = AddressInput("PRIVATE_ADDRESS"))
        val session = sessionService.create(scenario, SessionMode.CARD, studentId = student.id, groupId = group.id)
        sessionService.markReady(session.id)
        sessionService.startCard(session.id)
        sessionService.updateCard(session.id, OperatorCard(input, classifier.calculate(input)))
        sessionService.complete(session.id)
        sessionService.startScoring(session.id)
        sessionService.completeScoring(session.id)
        val proposal = mvc.perform(post("/api/student/scenario-proposals").session(studentSession).with(csrf())
            .contentType(MediaType.APPLICATION_JSON).content("{\"sessionId\":\"${session.id}\"}"))
            .andReturn()
        assertEquals(201, proposal.response.status, proposal.response.contentAsString)
        assertEquals("STUDENT", mapper.readTree(proposal.response.contentAsString)["source"].asText())
        val proposalId = mapper.readTree(proposal.response.contentAsString)["id"].asText()
        assertEquals(false, proposal.response.contentAsString.contains("PRIVATE_NAME"))
        assertEquals(false, proposal.response.contentAsString.contains("PRIVATE_PHONE"))
        assertEquals(false, proposal.response.contentAsString.contains("PRIVATE_ADDRESS"))
        assertEquals(409, mvc.perform(post("/api/student/scenario-proposals").session(studentSession).with(csrf())
            .contentType(MediaType.APPLICATION_JSON).content("{\"sessionId\":\"${session.id}\"}"))
            .andReturn().response.status)
        assertEquals(true, mvc.perform(get("/api/teacher/scenarios/workflow").session(teacherSession))
            .andReturn().response.contentAsString.contains(proposalId))
        assertEquals(200, mvc.perform(post("/api/teacher/scenarios/workflow/$proposalId/approve?expectedRevision=0")
            .session(teacherSession).with(csrf())).andReturn().response.status)
        assertEquals(201, mvc.perform(post("/api/teacher/scenarios/workflow/$proposalId/assign")
            .session(teacherSession).with(csrf()).contentType(MediaType.APPLICATION_JSON)
            .content("{\"studentId\":\"${student.id}\"}")).andReturn().response.status)
    }
}
