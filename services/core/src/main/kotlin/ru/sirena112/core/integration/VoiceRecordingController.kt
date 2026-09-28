package ru.sirena112.core.integration

import org.springframework.beans.factory.annotation.Value
import org.springframework.core.io.FileSystemResource
import org.springframework.http.HttpHeaders
import org.springframework.http.HttpStatus
import org.springframework.http.MediaType
import org.springframework.http.ResponseEntity
import org.springframework.web.bind.annotation.GetMapping
import org.springframework.web.bind.annotation.PathVariable
import org.springframework.web.bind.annotation.RequestMapping
import org.springframework.web.bind.annotation.RestController
import org.springframework.web.server.ResponseStatusException
import ru.sirena112.core.auth.SessionAccess
import ru.sirena112.core.domain.SessionEvent
import ru.sirena112.core.domain.SessionEventRepository
import ru.sirena112.core.domain.SessionEventType
import ru.sirena112.core.domain.SessionMode
import ru.sirena112.core.domain.SessionState
import ru.sirena112.core.domain.TrainingSessionRepository
import java.nio.file.Files
import java.nio.file.Path
import java.nio.file.LinkOption
import java.util.UUID

data class VoiceReview(
    val sessionId: UUID,
    val callId: UUID,
    val durationMs: Long,
    val bytes: Long,
    val format: String,
    val recordingUrl: String,
    val transcript: List<SessionEvent>,
    val events: List<SessionEvent>
)

@RestController
@RequestMapping("/api/teacher/sessions/{sessionId}")
class VoiceRecordingController(
    private val access: SessionAccess,
    private val sessions: TrainingSessionRepository,
    private val events: SessionEventRepository,
    @Value("\${core.recordings-dir:}") private val recordingsDir: String,
    @Value("\${core.auth.enabled:false}") private val authEnabled: Boolean
) {
    @GetMapping("/review")
    fun review(@PathVariable sessionId: UUID): VoiceReview {
        val record = locate(sessionId)
        val timeline = events.findBySessionId(sessionId)
        val transcripts = timeline
            .filter { it.type == SessionEventType.TRANSCRIPT_FINAL.value && it.payload["callId"] == record.callId.toString() }
            .sortedWith(compareBy<SessionEvent> { (it.payload["sequence"] as? Number)?.toLong() ?: Long.MAX_VALUE }
                .thenBy { it.timestamp })
        return VoiceReview(sessionId, record.callId, record.durationMs, record.bytes, "wav",
            "/api/teacher/sessions/$sessionId/recording", transcripts, timeline)
    }

    @GetMapping("/recording")
    fun recording(@PathVariable sessionId: UUID): ResponseEntity<FileSystemResource> {
        val record = locate(sessionId)
        val file = record.path
        return ResponseEntity.ok()
            .contentType(MediaType.parseMediaType("audio/wav"))
            .contentLength(Files.size(file))
            .header(HttpHeaders.CACHE_CONTROL, "no-store")
            .header(HttpHeaders.CONTENT_DISPOSITION, "attachment; filename=\"${record.callId}.wav\"")
            .body(FileSystemResource(file))
    }

    private data class Located(val callId: UUID, val durationMs: Long, val bytes: Long, val path: Path)

    private fun locate(sessionId: UUID): Located {
        // Without group-aware auth, a recording must never become publicly readable.
        if (!authEnabled) throw ResponseStatusException(HttpStatus.FORBIDDEN, "Доступ к записям требует авторизации")
        access.teacherCanRead(sessionId)
        val session = sessions.findById(sessionId) ?: throw ResponseStatusException(HttpStatus.NOT_FOUND)
        if (session.mode != SessionMode.VOICE || session.state != SessionState.COMPLETED) {
            throw ResponseStatusException(HttpStatus.NOT_FOUND)
        }
        if (recordingsDir.isBlank()) throw ResponseStatusException(HttpStatus.NOT_FOUND)
        val ready = events.findBySessionId(sessionId).lastOrNull { it.type == SessionEventType.RECORDING_READY.value }
            ?: throw ResponseStatusException(HttpStatus.NOT_FOUND)
        val callId = (ready.payload["callId"] as? String)?.let { runCatching { UUID.fromString(it) }.getOrNull() }
            ?: throw ResponseStatusException(HttpStatus.NOT_FOUND)
        if (ready.payload["recordingId"] != callId.toString() || ready.payload["format"] != "wav") {
            throw ResponseStatusException(HttpStatus.NOT_FOUND)
        }
        val duration = (ready.payload["durationMs"] as? Number)?.toLong() ?: 0
        val bytes = (ready.payload["bytes"] as? Number)?.toLong() ?: 0
        if (duration <= 0 || bytes < 44) throw ResponseStatusException(HttpStatus.NOT_FOUND)
        val root = Path.of(recordingsDir).toAbsolutePath().normalize()
        val directory = root.resolve(sessionId.toString())
        val file = directory.resolve("$callId.wav").normalize()
        if (!file.startsWith(root) || !Files.isDirectory(directory, LinkOption.NOFOLLOW_LINKS) ||
            !Files.isRegularFile(file, LinkOption.NOFOLLOW_LINKS) || Files.size(file) != bytes) {
            throw ResponseStatusException(HttpStatus.NOT_FOUND)
        }
        return Located(callId, duration, bytes, file)
    }
}
