package ru.sirena112.core.integration

import com.fasterxml.jackson.module.kotlin.jacksonObjectMapper
import org.junit.jupiter.api.Assertions.*
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.assertThrows
import org.junit.jupiter.api.io.TempDir
import org.springframework.http.HttpStatus
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken
import org.springframework.security.core.authority.SimpleGrantedAuthority
import org.springframework.security.core.context.SecurityContextHolder
import org.springframework.web.server.ResponseStatusException
import ru.sirena112.core.auth.*
import ru.sirena112.core.classifier.CardScenarioFixtures
import ru.sirena112.core.domain.*
import java.nio.file.Files
import java.nio.file.Path
import java.util.UUID

class VoiceRecordingControllerTest {
    @TempDir lateinit var root: Path

    @Test fun `two recordings and transcripts stay within their call and teacher group`() {
        val accounts = InMemoryAccountRepository()
        val sessions = InMemoryTrainingSessionRepository()
        val events = InMemorySessionEventRepository()
        val service = TrainingSessionService(sessions, events)
        val groupA = UUID.randomUUID()
        val groupB = UUID.randomUUID()
        val teacherA = AuthAccount(UUID.randomUUID(), "teacher-a", "", Role.TEACHER, "A", groupA)
        val teacherB = AuthAccount(UUID.randomUUID(), "teacher-b", "", Role.TEACHER, "B", groupB)
        accounts.insert(teacherA); accounts.insert(teacherB)
        val access = SessionAccess(accounts, sessions, InMemoryAuthAuditRepository(), true)
        val controller = VoiceRecordingController(access, sessions, events, root.toString(), true)
        val scenario = CardScenarioFixtures(jacksonObjectMapper()).load(Path.of("../../contracts/examples/scenario-1050602.json"))
        val calls = (0..1).map {
            val session = service.create(scenario, SessionMode.VOICE, groupId = if (it == 0) groupA else groupB)
            service.markReady(session.id); service.answer(session.id)
            val call = UUID.randomUUID()
            val dir = root.resolve(session.id.toString())
            Files.createDirectories(dir)
            Files.write(dir.resolve("$call.wav"), ByteArray(48) { b -> if (b == 0) 'R'.code.toByte() else it.toByte() })
            fun save(type: SessionEventType, payload: Map<String, Any?>) {
                events.saveIfAbsent(SessionEvent.create(session.id, type, EventSource.MEDIA, payload + ("callId" to call.toString())))
            }
            save(SessionEventType.TRANSCRIPT_FINAL, mapOf("text" to "second-$it", "sequence" to 2))
            save(SessionEventType.TRANSCRIPT_FINAL, mapOf("text" to "first-$it", "sequence" to 1))
            save(SessionEventType.RECORDING_READY, mapOf("recordingId" to call.toString(), "durationMs" to 20, "bytes" to 48, "format" to "wav"))
            service.complete(session.id)
            session.id to call
        }
        try {
            for ((teacher, own, foreign) in listOf(Triple(teacherA, calls[0], calls[1]), Triple(teacherB, calls[1], calls[0]))) {
                SecurityContextHolder.getContext().authentication = UsernamePasswordAuthenticationToken(
                    teacher.username, null, listOf(SimpleGrantedAuthority("ROLE_TEACHER")))
                val review = controller.review(own.first)
                assertEquals(own.second, review.callId)
                assertEquals(listOf("first-${if (teacher == teacherA) 0 else 1}", "second-${if (teacher == teacherA) 0 else 1}"), review.transcript.map { it.payload["text"] })
                assertTrue(review.events.any { it.type == SessionEventType.SESSION_COMPLETED.value })
                assertEquals(48, controller.recording(own.first).body!!.contentLength())
                assertEquals('R'.code.toByte(), controller.recording(own.first).body!!.inputStream.use { it.read() }.toByte())
                assertEquals(HttpStatus.FORBIDDEN, assertThrows<ResponseStatusException> { controller.recording(foreign.first) }.status)
            }
        } finally {
            SecurityContextHolder.clearContext()
        }
        val disabled = VoiceRecordingController(access, sessions, events, root.toString(), false)
        assertEquals(HttpStatus.FORBIDDEN, assertThrows<ResponseStatusException> { disabled.recording(calls[0].first) }.status)
    }
}
