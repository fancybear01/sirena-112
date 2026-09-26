package ru.sirena112.core.auth

import com.fasterxml.jackson.databind.ObjectMapper
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertThrows
import org.junit.jupiter.api.Test
import org.springframework.beans.factory.annotation.Autowired
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc
import org.springframework.boot.test.context.SpringBootTest
import org.springframework.http.MediaType
import org.springframework.mock.web.MockHttpSession
import org.springframework.security.test.web.servlet.request.SecurityMockMvcRequestPostProcessors.csrf
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken
import org.springframework.security.core.context.SecurityContextHolder
import org.springframework.security.core.userdetails.UserDetailsService
import org.springframework.web.server.ResponseStatusException
import org.springframework.test.web.servlet.MockMvc
import org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get
import org.springframework.test.web.servlet.request.MockMvcRequestBuilders.patch
import org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post
import java.util.UUID

@SpringBootTest(properties = [
    "core.auth.enabled=true",
    "core.auth.bootstrap-admin-username=admin",
    "core.auth.bootstrap-admin-password=admin-password-for-tests",
    "core.auth.media-token=0123456789abcdef0123456789abcdef"
])
@AutoConfigureMockMvc
class AuthIntegrationTest {
    @Autowired lateinit var mvc: MockMvc
    @Autowired lateinit var mapper: ObjectMapper
    @Autowired lateinit var access: SessionAccess
    @Autowired lateinit var details: UserDetailsService

    private fun login(username: String, password: String): MockHttpSession {
        val response = mvc.perform(post("/api/auth/login").with(csrf())
            .contentType(MediaType.APPLICATION_JSON)
            .content(mapper.writeValueAsString(LoginRequest(username, password)))).andReturn()
        assertEquals(200, response.response.status, response.response.contentAsString)
        return response.request.session as MockHttpSession
    }

    @Test fun `anonymous and service endpoints require credentials`() {
        assertEquals(401, mvc.perform(get("/api/student/assignments")).andReturn().response.status)
        assertEquals(401, mvc.perform(post("/internal/v1/media/events").contentType(MediaType.APPLICATION_JSON)
            .content("{}")).andReturn().response.status)
        assertEquals(401, mvc.perform(post("/api/auth/login").with(csrf()).contentType(MediaType.APPLICATION_JSON)
            .content("{\"username\":\"admin\",\"password\":\"wrong\"}")).andReturn().response.status)
    }

    @Test fun `teacher group and student ownership enforced including after lock`() {
        val admin = login("admin", "admin-password-for-tests")
        fun createGroup(): String {
            val response = mvc.perform(post("/api/admin/groups").session(admin).with(csrf())
                .contentType(MediaType.APPLICATION_JSON)
                .content("{\"name\":\"group-${UUID.randomUUID()}\"}")).andReturn()
            assertEquals(201, response.response.status)
            return mapper.readTree(response.response.contentAsString)["id"].asText()
        }
        val groupA = createGroup()
        val groupB = createGroup()
        fun createUser(role: String, group: String): Pair<String, String> {
            val username = "u${UUID.randomUUID().toString().replace("-", "").take(12)}"
            val response = mvc.perform(post("/api/admin/users").session(admin).with(csrf())
                .contentType(MediaType.APPLICATION_JSON)
                .content("""{"username":"$username","password":"student-password-123", "role":"$role",
                    "displayName":"Test User","groupId":"$group"}""")).andReturn()
            assertEquals(201, response.response.status, response.response.contentAsString)
            return username to mapper.readTree(response.response.contentAsString)["id"].asText()
        }
        val teacherA = createUser("TEACHER", groupA)
        val teacherB = createUser("TEACHER", groupB)
        val studentA = createUser("STUDENT", groupA)
        val studentB = createUser("STUDENT", groupB)
        val teacherASession = login(teacherA.first, "student-password-123")
        val teacherBSession = login(teacherB.first, "student-password-123")
        val studentASession = login(studentA.first, "student-password-123")
        val studentBSession = login(studentB.first, "student-password-123")

        val created = mvc.perform(post("/api/teacher/sessions").session(teacherASession).with(csrf())
            .contentType(MediaType.APPLICATION_JSON)
            .content("{\"studentId\":\"${studentA.second}\"}")).andReturn()
        assertEquals(201, created.response.status, created.response.contentAsString)
        val sessionId = mapper.readTree(created.response.contentAsString)["id"].asText()
        assertEquals(403, mvc.perform(post("/api/teacher/sessions").session(teacherASession).with(csrf())
            .contentType(MediaType.APPLICATION_JSON).content("{\"studentId\":\"${studentB.second}\"}"))
            .andReturn().response.status)
        assertEquals(403, mvc.perform(get("/api/teacher/sessions/$sessionId").session(teacherBSession))
            .andReturn().response.status)
        assertEquals(403, mvc.perform(get("/api/student/sessions/$sessionId").session(studentBSession))
            .andReturn().response.status)
        val foreign = details.loadUserByUsername(studentB.first)
        SecurityContextHolder.getContext().authentication = UsernamePasswordAuthenticationToken(
            foreign, null, foreign.authorities)
        try {
            assertEquals(403, assertThrows(ResponseStatusException::class.java) {
                access.websocket(UUID.fromString(sessionId))
            }.status.value())
        } finally {
            SecurityContextHolder.clearContext()
        }
        assertEquals(200, mvc.perform(get("/api/student/sessions/$sessionId").session(studentASession))
            .andReturn().response.status)
        val assignments = mvc.perform(get("/api/student/assignments").session(studentBSession)).andReturn()
        assertEquals(false, assignments.response.contentAsString.contains(sessionId))
        assertEquals(403, mvc.perform(post("/api/teacher/sessions/$sessionId/start").session(admin).with(csrf()))
            .andReturn().response.status)

        assertEquals(200, mvc.perform(patch("/api/admin/users/${studentA.second}/lock").session(admin).with(csrf())
            .contentType(MediaType.APPLICATION_JSON).content("{\"locked\":true}")).andReturn().response.status)
        assertEquals(401, mvc.perform(get("/api/student/sessions/$sessionId").session(studentASession))
            .andReturn().response.status)

        assertEquals(200, mvc.perform(patch("/api/admin/users/${studentB.second}/role").session(admin).with(csrf())
            .contentType(MediaType.APPLICATION_JSON)
            .content("{\"role\":\"TEACHER\",\"groupId\":\"$groupB\"}")).andReturn().response.status)
        assertEquals(401, mvc.perform(get("/api/student/assignments").session(studentBSession))
            .andReturn().response.status)
        assertEquals(204, mvc.perform(post("/api/auth/logout").session(teacherASession).with(csrf()))
            .andReturn().response.status)
        assertEquals(401, mvc.perform(get("/api/teacher/sessions/$sessionId").session(teacherASession))
            .andReturn().response.status)
    }
}
