package ru.sirena112.core.card

import com.fasterxml.jackson.databind.ObjectMapper
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Test
import org.springframework.beans.factory.annotation.Autowired
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc
import org.springframework.boot.test.context.SpringBootTest
import org.springframework.http.MediaType
import org.springframework.mock.web.MockHttpSession
import org.springframework.security.crypto.password.PasswordEncoder
import org.springframework.security.test.web.servlet.request.SecurityMockMvcRequestPostProcessors.csrf
import org.springframework.test.web.servlet.MockMvc
import org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get
import org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post
import ru.sirena112.core.auth.AccountRepository
import ru.sirena112.core.auth.AuthAccount
import ru.sirena112.core.auth.GroupRepository
import ru.sirena112.core.auth.Role
import ru.sirena112.core.auth.TrainingGroup
import ru.sirena112.core.domain.ScenarioRepository
import ru.sirena112.core.domain.SessionMode
import ru.sirena112.core.domain.TrainingSessionService
import java.util.UUID

@SpringBootTest(properties = ["core.auth.enabled=true", "core.auth.bootstrap-admin-username=admin",
    "core.auth.bootstrap-admin-password=admin-password-for-tests",
    "core.auth.media-token=0123456789abcdef0123456789abcdef"])
@AutoConfigureMockMvc
class TrainingHistoryIntegrationTest {
    @Autowired lateinit var mvc: MockMvc
    @Autowired lateinit var mapper: ObjectMapper
    @Autowired lateinit var accounts: AccountRepository
    @Autowired lateinit var groups: GroupRepository
    @Autowired lateinit var encoder: PasswordEncoder
    @Autowired lateinit var scenarios: ScenarioRepository
    @Autowired lateinit var sessions: TrainingSessionService
    @Autowired lateinit var reports: SessionReportRepository

    private fun account(role: Role, group: TrainingGroup): AuthAccount = AuthAccount(UUID.randomUUID(),
        "u${UUID.randomUUID().toString().replace("-", "").take(12)}", encoder.encode("password-for-tests"),
        role, role.name, group.id).also(accounts::insert)

    private fun login(user: AuthAccount): MockHttpSession {
        val result = mvc.perform(post("/api/auth/login").with(csrf()).contentType(MediaType.APPLICATION_JSON)
            .content("""{"username":"${user.username}","password":"password-for-tests"}""")).andReturn()
        assertEquals(200, result.response.status)
        return result.request.session as MockHttpSession
    }

    private fun loginAdmin(): MockHttpSession {
        val result = mvc.perform(post("/api/auth/login").with(csrf()).contentType(MediaType.APPLICATION_JSON)
            .content("""{"username":"admin","password":"admin-password-for-tests"}""")).andReturn()
        assertEquals(200, result.response.status)
        return result.request.session as MockHttpSession
    }

    @Test fun `history is scoped and corrections preserve original score`() {
        val groupA = TrainingGroup(UUID.randomUUID(), "history-a-${UUID.randomUUID()}").also(groups::insert)
        val groupB = TrainingGroup(UUID.randomUUID(), "history-b-${UUID.randomUUID()}").also(groups::insert)
        val teacherAccount = account(Role.TEACHER, groupA)
        val teacherA = login(teacherAccount)
        val teacherB = login(account(Role.TEACHER, groupB))
        val studentA = account(Role.STUDENT, groupA)
        val studentB = account(Role.STUDENT, groupB)
        val studentSameGroup = account(Role.STUDENT, groupA)
        val studentASession = login(studentA)
        val studentBSession = login(studentB)
        val studentSameGroupSession = login(studentSameGroup)
        val adminSession = loginAdmin()
        val scenario = scenarios.findAll().first()
        val first = sessions.create(scenario, SessionMode.CARD, studentId = studentA.id, teacherId = teacherAccount.id, groupId = groupA.id)
        val second = sessions.create(scenario, SessionMode.CARD, studentId = studentA.id, teacherId = teacherAccount.id, groupId = groupA.id)
        val foreign = sessions.create(scenario, SessionMode.CARD, studentId = studentB.id, groupId = groupB.id)
        val pending = sessions.create(scenario, SessionMode.CARD, studentId = studentA.id, teacherId = teacherAccount.id, groupId = groupA.id)
        listOf(first, second, foreign).forEachIndexed { index, session ->
            sessions.markReady(session.id)
            sessions.startCard(session.id)
            sessions.complete(session.id)
            sessions.startScoring(session.id)
            reports.save(SessionReport(session.id, 60.0 + index, 100.0, false, emptyList(), emptyList(), emptyList()))
            sessions.completeScoring(session.id)
        }
        fun read(path: String, session: MockHttpSession) = mvc.perform(get(path).session(session)).andReturn()
        val teacherHistory = read("/api/teacher/history", teacherA)
        assertEquals(200, teacherHistory.response.status)
        val teacherAttempts = mapper.readTree(teacherHistory.response.contentAsString)["attempts"]
        assertEquals(2, teacherAttempts.count { it["sessionId"].asText() in setOf(first.id.toString(), second.id.toString()) })
        assertEquals(true, mapper.readTree(read("/api/student/history/${pending.id}", studentASession)
            .response.contentAsString)["comparison"].isNull)
        assertEquals(false, teacherHistory.response.contentAsString.contains(foreign.id.toString()))
        assertEquals(403, read("/api/teacher/history/${first.id}", teacherB).response.status)
        assertEquals(403, read("/api/student/history/${first.id}", studentBSession).response.status)
        assertEquals(403, read("/api/student/history/${first.id}", studentSameGroupSession).response.status)
        assertEquals(false, read("/api/student/history", studentASession).response.contentAsString.contains(foreign.id.toString()))
        assertEquals(200, read("/api/teacher/history/${first.id}", adminSession).response.status)
        assertEquals(403, mvc.perform(post("/api/teacher/history/${first.id}/corrections").session(adminSession).with(csrf())
            .contentType(MediaType.APPLICATION_JSON).content("""{"newScore":99,"reason":"admin attempt"}"""))
            .andReturn().response.status)

        val comment = mvc.perform(post("/api/teacher/history/${first.id}/comments").session(teacherA).with(csrf())
            .contentType(MediaType.APPLICATION_JSON).content("""{"text":"Разберите маршрутизацию"}""")).andReturn()
        assertEquals(201, comment.response.status)
        val correction = mvc.perform(post("/api/teacher/history/${first.id}/corrections").session(teacherA).with(csrf())
            .contentType(MediaType.APPLICATION_JSON).content("""{"newScore":75,"reason":"Проверено по эталону"}""")).andReturn()
        assertEquals(201, correction.response.status, correction.response.contentAsString)
        val studentView = mapper.readTree(read("/api/student/history/${first.id}", studentASession).response.contentAsString)
        assertEquals(60.0, studentView["originalReport"]["score"].asDouble())
        assertEquals(75.0, studentView["effectiveScore"].asDouble())
        assertEquals(scenario.groundTruth.classifierCode, studentView["comparison"]["expectedClassifierCode"].asText())
        assertEquals(2, studentView["feedback"].size())
        assertEquals(60.0, reports.findBySessionId(first.id).score)
        assertEquals(false, mapper.readTree(read("/api/student/history/${first.id}", studentASession)
            .response.contentAsString)["comparison"].isNull)
        assertEquals(403, mvc.perform(post("/api/teacher/history/${first.id}/comments").session(teacherB).with(csrf())
            .contentType(MediaType.APPLICATION_JSON).content("""{"text":"no"}""")).andReturn().response.status)
    }
}
