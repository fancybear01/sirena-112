package ru.sirena112.core.integration

import org.springframework.http.HttpStatus
import org.springframework.web.bind.annotation.GetMapping
import org.springframework.web.bind.annotation.PathVariable
import org.springframework.web.bind.annotation.PostMapping
import org.springframework.web.bind.annotation.RequestBody
import org.springframework.web.bind.annotation.RequestMapping
import org.springframework.web.bind.annotation.ResponseStatus
import org.springframework.web.bind.annotation.RestController
import ru.sirena112.core.domain.SessionEvent
import ru.sirena112.core.domain.SessionState
import ru.sirena112.core.domain.TrainingSessionRepository
import java.util.UUID

data class StartVoiceCallRequest(val sipAddress: String)
data class MediaEventReceipt(val eventId: UUID, val accepted: Boolean, val sessionState: SessionState)

@RestController
@RequestMapping("/api/teacher/sessions")
class VoiceTrainingController(private val voice: VoiceTrainingService,
    private val access: ru.sirena112.core.auth.SessionAccess) {
    @PostMapping("/{sessionId}/call/start")
    @ResponseStatus(HttpStatus.ACCEPTED)
    fun start(@PathVariable sessionId: UUID, @RequestBody request: StartVoiceCallRequest): VoiceCallView =
        voice.start(sessionId.also(access::teacherCanWrite), request.sipAddress)

    @PostMapping("/{sessionId}/call/hangup")
    fun hangup(@PathVariable sessionId: UUID): VoiceCallView = voice.hangup(sessionId.also(access::teacherCanWrite))

    @GetMapping("/{sessionId}/call")
    fun call(@PathVariable sessionId: UUID): VoiceCallView = voice.getCall(sessionId.also(access::teacherCanRead))

    @GetMapping("/{sessionId}/events")
    fun events(@PathVariable sessionId: UUID): List<SessionEvent> = voice.events(sessionId.also(access::teacherCanRead))
}

@RestController
@RequestMapping("/internal/v1/media")
class MediaEventController(
    private val voice: VoiceTrainingService,
    private val sessions: TrainingSessionRepository
) {
    @PostMapping("/events")
    fun receive(@RequestBody event: SessionEvent): MediaEventReceipt {
        val accepted = voice.receive(event)
        return MediaEventReceipt(event.eventId, accepted, sessions.findById(event.sessionId)!!.state)
    }
}
