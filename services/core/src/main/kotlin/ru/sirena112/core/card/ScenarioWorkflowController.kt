package ru.sirena112.core.card

import com.fasterxml.jackson.databind.ObjectMapper
import com.networknt.schema.JsonSchemaFactory
import com.networknt.schema.SpecVersion
import org.springframework.beans.factory.annotation.Qualifier
import org.springframework.http.HttpEntity
import org.springframework.http.HttpMethod
import org.springframework.http.HttpStatus
import org.springframework.http.HttpHeaders
import org.springframework.http.MediaType
import org.springframework.stereotype.Service
import org.springframework.transaction.annotation.Transactional
import org.springframework.web.bind.annotation.*
import org.springframework.web.client.RestTemplate
import org.springframework.web.server.ResponseStatusException
import ru.sirena112.core.auth.AccountRepository
import ru.sirena112.core.auth.AuthAudit
import ru.sirena112.core.auth.AuthAuditRepository
import ru.sirena112.core.auth.Role
import ru.sirena112.core.auth.SessionAccess
import ru.sirena112.core.classifier.CalculationStatus
import ru.sirena112.core.classifier.ClassifierCatalog
import ru.sirena112.core.classifier.ClassifierService
import ru.sirena112.core.classifier.OperatorCardInput
import ru.sirena112.core.classifier.IncidentInput
import ru.sirena112.core.classifier.AddressInput
import ru.sirena112.core.config.CoreProperties
import ru.sirena112.core.domain.Scenario
import ru.sirena112.core.domain.GroundTruth
import ru.sirena112.core.domain.SessionMode
import ru.sirena112.core.domain.SessionState
import ru.sirena112.core.domain.TrainingSessionRepository
import ru.sirena112.core.domain.ScenarioCategory
import ru.sirena112.core.domain.Difficulty
import ru.sirena112.core.domain.ScenarioRepository
import java.util.UUID

data class DraftRequest(val scenario: Scenario, val comment: String = "", val expectedRevision: Int? = null)
data class GenerateDraftRequest(val category: ScenarioCategory, val difficulty: Difficulty, val seed: Int = 0,
    val comment: String = "")
data class ValidationResult(val valid: Boolean, val errors: List<String>)
data class AssignScenarioRequest(val studentId: UUID? = null, val groupId: UUID? = null)

@Service
class ScenarioIntegrity(private val mapper: ObjectMapper, private val catalog: ClassifierCatalog,
    private val classifier: ClassifierService) {
    private val schemaMapper = mapper.copy().setSerializationInclusion(com.fasterxml.jackson.annotation.JsonInclude.Include.NON_NULL)
    private val schema by lazy {
        JsonSchemaFactory.getInstance(SpecVersion.VersionFlag.V202012)
            .getSchema(mapper.readTree(catalog.contractsDir().resolve("scenario.schema.json").toFile()))
    }

    fun validate(scenario: Scenario): ValidationResult {
        val errors = schema.validate(schemaMapper.valueToTree(scenario)).map { it.message }.toMutableList()
        if (scenario.groundTruth.classifierVersion != catalog.classifierVersion) {
            errors += "Версия классификатора должна быть ${catalog.classifierVersion}"
        }
        val calculation = runCatching { classifier.calculate(scenario.groundTruth.expectedInput) }
            .getOrElse { errors += it.message ?: "Некорректные признаки/ответы"; return ValidationResult(false, errors) }
        val truth = scenario.groundTruth
        if (calculation.status != CalculationStatus.RESOLVED || calculation.classifierCode != truth.classifierCode ||
            calculation.incidentType != truth.incidentType || calculation.ekp35IncidentType != truth.ekp35IncidentType ||
            calculation.responseScenarioCode != truth.responseScenarioCode ||
            calculation.responseScenarioStatus != truth.responseScenarioStatus ||
            calculation.mainServices.map { it.id }.toSet() != truth.mainServices.map { it.id }.toSet() ||
            calculation.services.map { it.id }.toSet() != truth.requiredServices.map { it.id }.toSet()) {
            errors += "Эталон и службы не совпадают с официальным классификатором"
        }
        return ValidationResult(errors.isEmpty(), errors)
    }
}

@Service
class ScenarioWorkflowService(private val workflows: ScenarioWorkflowRepository,
    private val scenarios: ScenarioRepository, private val integrity: ScenarioIntegrity,
    private val sessions: TrainingSessionRepository, private val classifier: ClassifierService,
    private val access: SessionAccess, private val accounts: AccountRepository,
    private val facade: CardTrainingFacade, private val audit: AuthAuditRepository,
    @Qualifier("aiRestTemplate") private val aiHttp: RestTemplate, private val properties: CoreProperties,
    private val mapper: ObjectMapper) {

    fun list(): List<ScenarioWorkflow> {
        val actor = access.current() ?: return workflows.findAll()
        return workflows.findAll().filter { actor.role == Role.ADMIN ||
            actor.role == Role.TEACHER && actor.groupId != null && it.groupId == actor.groupId }
    }

    fun get(id: UUID): ScenarioWorkflow = visible(id)

    fun studentProposals(): List<ScenarioWorkflow> {
        val actor = access.current() ?: throw ResponseStatusException(HttpStatus.FORBIDDEN)
        if (actor.role != Role.STUDENT) throw ResponseStatusException(HttpStatus.FORBIDDEN)
        return workflows.findAll().filter { it.source == ScenarioSource.STUDENT && it.ownerId == actor.id }
    }

    fun proposeFromCard(sessionId: UUID): ScenarioWorkflow {
        val actor = access.current() ?: throw ResponseStatusException(HttpStatus.FORBIDDEN)
        if (actor.role != Role.STUDENT || actor.groupId == null) throw ResponseStatusException(HttpStatus.FORBIDDEN)
        access.studentOwns(sessionId)
        if (workflows.findAll().any { it.sourceSessionId == sessionId })
            throw ResponseStatusException(HttpStatus.CONFLICT, "Карточка уже предложена")
        val session = sessions.findById(sessionId) ?: throw ResponseStatusException(HttpStatus.NOT_FOUND)
        if (session.mode != SessionMode.CARD || session.state != SessionState.SCORED || session.cardRevision < 1)
            throw ResponseStatusException(HttpStatus.CONFLICT, "Предложение возможно только из оценённой карточки")
        val submitted = session.operatorCard.input
        val incident = submitted.incident ?: throw IllegalArgumentException("В карточке нет признаков происшествия")
        // Never copy free text, names, phone numbers, or the entered real-world address into a reusable scenario.
        val safeInput = OperatorCardInput(
            incident = IncidentInput(incident.selectedSignIds, incident.answers.map { it.copy(freeText = null) }),
            address = AddressInput("Учебный адрес без персональных данных"),
            victims = submitted.victims
        )
        val result = classifier.calculate(safeInput)
        if (result.status != CalculationStatus.RESOLVED ||
            result.classifierCode != session.scenario.groundTruth.classifierCode ||
            result.incidentType == null || result.responseScenarioStatus == null)
            throw ResponseStatusException(HttpStatus.UNPROCESSABLE_ENTITY,
                "Признаки карточки не образуют проверяемый вариант исходного типа происшествия")
        val id = UUID.randomUUID()
        val scenario = session.scenario.copy(id = id, version = 1,
            title = "${result.incidentType} — вариант обучающегося",
            profile = "Учебный вариант, созданный из обезличенной карточки обучающегося",
            groundTruth = GroundTruth(result.classifierVersion, result.classifierCode,
                result.incidentType, result.ekp35IncidentType, result.responseScenarioCode,
                result.responseScenarioStatus, result.mainServices, result.services, safeInput), caller = null)
        val validation = integrity.validate(scenario)
        if (!validation.valid) throw ResponseStatusException(HttpStatus.UNPROCESSABLE_ENTITY, validation.errors.joinToString("; "))
        val proposal = ScenarioWorkflow(id, id, 1, 0, ScenarioStatus.DRAFT, scenario,
            "Предложено из завершённого занятия; проверить перед утверждением", actor.id, actor.groupId,
            ScenarioSource.STUDENT, sessionId)
        workflows.insert(proposal)
        record(actor.id, "SCENARIO_PROPOSED", id)
        return proposal
    }

    fun create(request: DraftRequest, source: ScenarioSource = ScenarioSource.MANUAL): ScenarioWorkflow {
        val actor = teacher()
        require(request.comment.length <= 4000) { "Комментарий слишком длинный" }
        val id = UUID.randomUUID()
        val scenario = request.scenario.copy(id = id, version = 1)
        val item = ScenarioWorkflow(id, id, 1, 0, ScenarioStatus.DRAFT, scenario,
            request.comment, actor?.id, actor?.groupId, source)
        workflows.insert(item)
        record(actor?.id, "SCENARIO_DRAFT_CREATED", id)
        return item
    }

    fun generate(request: GenerateDraftRequest): ScenarioWorkflow {
        teacher()
        require(request.seed >= 0) { "seed не может быть отрицательным" }
        val headers = HttpHeaders().apply {
            contentType = MediaType.APPLICATION_JSON
            System.getenv("AI_SERVICE_TOKEN")?.takeIf { it.isNotBlank() }?.let { setBearerAuth(it) }
        }
        val response = try {
            aiHttp.exchange("${properties.aiBaseUrl.trimEnd('/')}/ai/scenarios/generate", HttpMethod.POST,
                HttpEntity(mapOf("category" to request.category.name, "difficulty" to request.difficulty.name,
                    "count" to 1, "seed" to request.seed), headers), com.fasterxml.jackson.databind.JsonNode::class.java).body
        } catch (exception: Exception) {
            throw ResponseStatusException(HttpStatus.BAD_GATEWAY, "AI-генерация недоступна", exception)
        }
        val generated = response?.path("scenarios")?.firstOrNull()
            ?: throw ResponseStatusException(HttpStatus.BAD_GATEWAY, "AI не предложил сценарий выбранного уровня")
        val scenario = mapper.treeToValue(generated, Scenario::class.java)
        return create(DraftRequest(scenario, request.comment), ScenarioSource.AI)
    }

    fun edit(id: UUID, request: DraftRequest): ScenarioWorkflow {
        val old = editable(id)
        val expected = request.expectedRevision ?: throw IllegalArgumentException("Укажите expectedRevision")
        require(request.comment.length <= 4000) { "Комментарий слишком длинный" }
        val next = old.copy(revision = old.revision + 1,
            scenario = request.scenario.copy(id = id, version = old.version), comment = request.comment)
        if (!workflows.updateDraft(next, expected)) throw ResponseStatusException(HttpStatus.CONFLICT, "Черновик изменён другим пользователем")
        record(access.current()?.id, "SCENARIO_DRAFT_EDITED", id)
        return next
    }

    fun validate(id: UUID): ValidationResult = integrity.validate(visible(id).scenario)

    @Transactional
    fun approve(id: UUID, expectedRevision: Int): ScenarioWorkflow {
        val old = editable(id)
        val result = integrity.validate(old.scenario)
        if (!result.valid) throw IllegalArgumentException(result.errors.joinToString("; "))
        if (scenarios.findById(id) != null) throw ResponseStatusException(HttpStatus.CONFLICT, "Версия уже утверждена")
        val next = old.copy(status = ScenarioStatus.APPROVED, revision = old.revision + 1)
        if (!workflows.updateDraft(next, expectedRevision)) throw ResponseStatusException(HttpStatus.CONFLICT, "Черновик изменён другим пользователем")
        scenarios.save(next.scenario)
        record(access.current()?.id, "SCENARIO_APPROVED", id)
        return next
    }

    fun fork(id: UUID): ScenarioWorkflow {
        val old = visible(id)
        if (old.status != ScenarioStatus.APPROVED) throw ResponseStatusException(HttpStatus.CONFLICT, "Можно версионировать только утверждённый сценарий")
        val actor = teacher()
        val version = workflows.findAll().filter { it.familyId == old.familyId }.maxOf { it.version } + 1
        val nextId = UUID.randomUUID()
        val next = ScenarioWorkflow(nextId, old.familyId, version, 0, ScenarioStatus.DRAFT,
            old.scenario.copy(id = nextId, version = version), old.comment, actor?.id, actor?.groupId, ScenarioSource.COPY)
        workflows.insert(next)
        record(actor?.id, "SCENARIO_VERSION_CREATED", nextId)
        return next
    }

    @Transactional
    fun assign(id: UUID, request: AssignScenarioRequest): List<SessionView> {
        val item = visible(id)
        if (item.status != ScenarioStatus.APPROVED) throw ResponseStatusException(HttpStatus.CONFLICT, "Нельзя назначить черновик")
        val actor = teacher()
        val students = when {
            request.studentId != null && request.groupId == null -> listOf(request.studentId)
            request.groupId != null && request.studentId == null -> {
                if (actor == null || actor.groupId != request.groupId) throw ResponseStatusException(HttpStatus.FORBIDDEN)
                accounts.findAll().filter { it.role == Role.STUDENT && it.groupId == request.groupId && !it.locked && it.enabled }.map { it.id }
            }
            else -> throw IllegalArgumentException("Укажите studentId или groupId")
        }
        require(students.isNotEmpty()) { "В группе нет активных студентов" }
        return students.map { studentId ->
            val session = facade.createSession(CreateCardSessionRequest(id, studentId = studentId))
            facade.start(session.id)
        }.also { record(actor?.id, "SCENARIO_ASSIGNED", id) }
    }

    private fun visible(id: UUID): ScenarioWorkflow {
        val item = workflows.findById(id) ?: throw ResponseStatusException(HttpStatus.NOT_FOUND)
        val actor = access.current() ?: return item
        if (actor.role == Role.ADMIN || actor.role == Role.TEACHER && actor.groupId != null && actor.groupId == item.groupId) return item
        throw ResponseStatusException(HttpStatus.FORBIDDEN)
    }

    private fun editable(id: UUID): ScenarioWorkflow {
        val item = visible(id)
        teacher()
        if (item.status != ScenarioStatus.DRAFT) throw ResponseStatusException(HttpStatus.CONFLICT, "Утверждённую версию нельзя менять")
        return item
    }

    private fun teacher() = access.current()?.also {
        if (it.role != Role.TEACHER || it.groupId == null) throw ResponseStatusException(HttpStatus.FORBIDDEN)
    }

    private fun record(actor: UUID?, action: String, subject: UUID) =
        audit.append(AuthAudit(actor, action, subject, "OK", null))
}

@RestController
@RequestMapping("/api/teacher/scenarios/workflow")
class ScenarioWorkflowController(private val service: ScenarioWorkflowService) {
    @GetMapping fun list(): List<ScenarioWorkflow> = service.list()
    @GetMapping("/{id}") fun get(@PathVariable id: UUID): ScenarioWorkflow = service.get(id)
    @PostMapping("/drafts") @ResponseStatus(HttpStatus.CREATED)
    fun create(@RequestBody request: DraftRequest): ScenarioWorkflow = service.create(request)
    @PostMapping("/drafts/generate") @ResponseStatus(HttpStatus.CREATED)
    fun generate(@RequestBody request: GenerateDraftRequest): ScenarioWorkflow = service.generate(request)
    @PutMapping("/{id}") fun edit(@PathVariable id: UUID, @RequestBody request: DraftRequest): ScenarioWorkflow = service.edit(id, request)
    @PostMapping("/{id}/validate") fun validate(@PathVariable id: UUID): ValidationResult = service.validate(id)
    @PostMapping("/{id}/approve") fun approve(@PathVariable id: UUID, @RequestParam expectedRevision: Int): ScenarioWorkflow =
        service.approve(id, expectedRevision)
    @PostMapping("/{id}/fork") @ResponseStatus(HttpStatus.CREATED)
    fun fork(@PathVariable id: UUID): ScenarioWorkflow = service.fork(id)
    @PostMapping("/{id}/assign") @ResponseStatus(HttpStatus.CREATED)
    fun assign(@PathVariable id: UUID, @RequestBody request: AssignScenarioRequest): List<SessionView> = service.assign(id, request)
}

@RestController
@RequestMapping("/api/student/scenario-proposals")
class StudentScenarioProposalController(private val service: ScenarioWorkflowService) {
    @GetMapping fun list(): List<ScenarioWorkflow> = service.studentProposals()
    @PostMapping @ResponseStatus(HttpStatus.CREATED)
    fun propose(@RequestBody request: StudentProposalRequest): ScenarioWorkflow = service.proposeFromCard(request.sessionId)
}

data class StudentProposalRequest(val sessionId: UUID)
