package ru.sirena112.core.card

import org.springframework.http.HttpStatus
import org.springframework.web.bind.annotation.GetMapping
import org.springframework.web.bind.annotation.PatchMapping
import org.springframework.web.bind.annotation.PathVariable
import org.springframework.web.bind.annotation.PostMapping
import org.springframework.web.bind.annotation.RequestBody
import org.springframework.web.bind.annotation.RequestMapping
import org.springframework.web.bind.annotation.ResponseStatus
import org.springframework.web.bind.annotation.RestController
import ru.sirena112.core.classifier.CardFormDefinition
import java.util.UUID

@RestController
@RequestMapping("/api/teacher")
class TeacherCardController(private val facade: CardTrainingFacade,
    private val access: ru.sirena112.core.auth.SessionAccess,
    private val accounts: ru.sirena112.core.auth.AccountRepository) {
    @GetMapping("/students")
    fun students(): List<ru.sirena112.core.auth.UserView> {
        val actor = access.current() ?: return emptyList()
        return accounts.findAll().filter { it.role == ru.sirena112.core.auth.Role.STUDENT && !it.locked && it.enabled &&
            (actor.role == ru.sirena112.core.auth.Role.ADMIN || it.groupId == actor.groupId) }
            .map(ru.sirena112.core.auth.UserView::from)
    }
    @GetMapping("/scenarios")
    fun scenarios(): List<ScenarioResponse> = facade.scenarios().map { ScenarioResponse.from(it) }

    @PostMapping("/sessions")
    @ResponseStatus(HttpStatus.CREATED)
    fun createSession(@RequestBody(required = false) request: CreateCardSessionRequest?): SessionView =
        facade.createSession(request ?: CreateCardSessionRequest())

    @GetMapping("/sessions/{sessionId}")
    fun get(@PathVariable sessionId: UUID): SessionView { access.teacherCanRead(sessionId); return facade.get(sessionId) }

    @PostMapping("/sessions/{sessionId}/start")
    fun start(@PathVariable sessionId: UUID): SessionView { access.teacherCanWrite(sessionId); return facade.start(sessionId) }

    @PostMapping("/sessions/{sessionId}/stop")
    fun stop(@PathVariable sessionId: UUID): SessionView { access.teacherCanWrite(sessionId); return facade.stop(sessionId) }

    @GetMapping("/sessions/{sessionId}/report")
    fun report(@PathVariable sessionId: UUID): SessionReport { access.teacherCanRead(sessionId); return facade.report(sessionId) }
}

@RestController
@RequestMapping("/api/student/sessions")
class StudentCardController(private val facade: CardTrainingFacade,
    private val access: ru.sirena112.core.auth.SessionAccess) {
    @GetMapping("/{sessionId}")
    fun get(@PathVariable sessionId: UUID): SessionView { access.studentOwns(sessionId); return facade.get(sessionId) }

    /** Форма для текущего черновика: допустимые признаки и зависимые вопросы. */
    @GetMapping("/{sessionId}/card-form")
    fun cardForm(@PathVariable sessionId: UUID): CardFormDefinition { access.studentOwns(sessionId); return facade.cardForm(sessionId) }

    @PatchMapping("/{sessionId}/card")
    fun saveCard(
        @PathVariable sessionId: UUID,
        @RequestBody request: SaveCardRequest
    ): SessionView { access.studentOwns(sessionId); return facade.saveCard(sessionId, request) }

    @PostMapping("/{sessionId}/submit")
    @ResponseStatus(HttpStatus.ACCEPTED)
    fun submit(
        @PathVariable sessionId: UUID,
        @RequestBody request: SubmitCardRequest
    ): SessionReport { access.studentOwns(sessionId); return facade.submit(sessionId, request) }
}

data class ScenarioResponse(
    val id: UUID,
    val version: Int,
    val title: String,
    val category: String,
    val difficulty: String,
    val profile: String,
    val timeLimitSeconds: Int,
    val groundTruth: Any,
    val rubric: Any
) {
    companion object {
        fun from(scenario: ru.sirena112.core.domain.Scenario): ScenarioResponse = ScenarioResponse(
            id = scenario.id,
            version = scenario.version,
            title = scenario.title,
            category = scenario.category.name,
            difficulty = scenario.difficulty.name,
            profile = scenario.profile,
            timeLimitSeconds = scenario.timeLimitSeconds,
            groundTruth = scenario.groundTruth,
            rubric = scenario.rubric
        )
    }
}

data class StudentAssignmentResponse(
    val scenario: ScenarioResponse,
    val session: SessionView
)

@RestController
@RequestMapping("/api/student")
class StudentAssignmentController(private val facade: CardTrainingFacade) {
    @GetMapping("/assignments")
    fun assignments(): List<StudentAssignmentResponse> = facade.assignments()
}
