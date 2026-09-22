package ru.sirena112.core.card

import org.springframework.context.annotation.Bean
import org.springframework.context.annotation.Configuration
import org.springframework.stereotype.Service
import org.springframework.transaction.annotation.Transactional
import ru.sirena112.core.classifier.CardCalculation
import ru.sirena112.core.classifier.CardFormDefinition
import ru.sirena112.core.classifier.CardScenarioFixtures
import ru.sirena112.core.classifier.ClassificationEngine
import ru.sirena112.core.classifier.ClassifierCatalog
import ru.sirena112.core.classifier.ClassifierService
import ru.sirena112.core.classifier.CalculationStatus
import ru.sirena112.core.classifier.OperatorCardInput
import ru.sirena112.core.domain.InMemoryScenarioRepository
import ru.sirena112.core.domain.InMemorySessionEventRepository
import ru.sirena112.core.domain.InMemoryTrainingSessionRepository
import ru.sirena112.core.domain.OperatorCard
import ru.sirena112.core.domain.Scenario
import ru.sirena112.core.domain.ScenarioRepository
import ru.sirena112.core.domain.SessionEventRepository
import ru.sirena112.core.domain.SessionEventType
import ru.sirena112.core.domain.SessionMode
import ru.sirena112.core.domain.SessionState
import ru.sirena112.core.domain.TrainingSession
import ru.sirena112.core.domain.TrainingSessionRepository
import ru.sirena112.core.domain.TrainingSessionService
import java.time.Duration
import java.util.UUID

/** Контракт 0.3: клиент отправляет только исходные данные оператора. */
data class CreateCardSessionRequest(val scenarioId: UUID? = null, val mode: SessionMode = SessionMode.CARD)

data class SaveCardRequest(
    val input: OperatorCardInput,
    val expectedRevision: Int? = null
)

data class SubmitCardRequest(
    val input: OperatorCardInput,
    val expectedRevision: Int? = null
)

data class CriterionScore(
    val code: String,
    val passed: Boolean,
    val points: Double,
    val maxPoints: Double,
    val message: String
)

data class ScoreError(
    val code: String,
    val message: String,
    val field: String? = null
)

data class SessionReport(
    val sessionId: UUID,
    val score: Double,
    val maxScore: Double,
    val passed: Boolean,
    val criteria: List<CriterionScore>,
    val errors: List<ScoreError>,
    val recommendations: List<String>,
    val classifierVersion: String? = null,
    val classifierCode: String? = null
)

data class SessionView(
    val id: UUID,
    val scenarioId: UUID,
    val mode: SessionMode,
    val state: SessionState,
    val card: OperatorCard,
    val cardRevision: Int,
    val startedAt: java.time.Instant?,
    val endedAt: java.time.Instant?,
    val timeLimitSeconds: Int,
    val timeLimitExceeded: Boolean,
    val report: SessionReport? = null
)

@Service
class CardTrainingFacade(
    private val scenarioRepository: ScenarioRepository,
    private val sessionRepository: TrainingSessionRepository,
    private val sessionService: TrainingSessionService,
    private val classifierService: ClassifierService,
    private val serviceAssignments: ru.sirena112.core.dispatch.ServiceAssignmentService,
    private val aiClient: ru.sirena112.core.integration.AiClient,
    private val reportRepository: SessionReportRepository
) {

    fun scenarios(): List<Scenario> = scenarioRepository.findAll().sortedBy { it.groundTruth.classifierCode }

    fun assignments(): List<StudentAssignmentResponse> = sessionRepository.findAll()
        .asSequence()
        .filter { it.mode == SessionMode.CARD }
        .filter { it.state in setOf(SessionState.ACTIVE, SessionState.SCORING, SessionState.SCORED) }
        .sortedWith(compareByDescending<TrainingSession> { it.state == SessionState.ACTIVE }
            .thenByDescending { it.startedAt ?: it.createdAt })
        .map { session ->
            StudentAssignmentResponse(
                scenario = ScenarioResponse.from(session.scenario),
                session = session.toView()
            )
        }
        .toList()

    fun cardForm(sessionId: UUID): CardFormDefinition {
        val session = requireCardSession(sessionId)
        return classifierService.buildForm(session.operatorCard.input)
    }

    fun createSession(request: CreateCardSessionRequest): SessionView {
        val scenario = scenarioRepository.findById(request.scenarioId ?: DEFAULT_SCENARIO_ID)
            ?: throw NoSuchElementException("Сценарий ${request.scenarioId} не найден")
        return sessionService.create(scenario, request.mode).toView()
    }

    fun start(sessionId: UUID): SessionView {
        val session = requireSession(sessionId)
        if (session.mode != SessionMode.CARD) throw IllegalStateException("Голосовая сессия запускается через /call/start")
        sessionService.markReady(session.id)
        return sessionService.startCard(session.id).toView()
    }

    fun stop(sessionId: UUID): SessionView = sessionService.complete(requireCardSession(sessionId).id).toView()

    fun get(sessionId: UUID): SessionView = requireSession(sessionId).toView()

    /** Сохранение черновика: черновик можно сохранять до полного заполнения. */
    @Transactional
    fun saveCard(sessionId: UUID, request: SaveCardRequest): SessionView {
        val session = requireCardSession(sessionId)
        if (request.input.isEmpty()) {
            throw IllegalArgumentException("Карточка должна содержать хотя бы одно заполненное поле")
        }
        session.checkRevision(request.expectedRevision)
        val calculation = classifierService.calculate(request.input)
        val card = OperatorCard(input = request.input, calculation = calculation)
        val updated = sessionService.updateCard(
            session.id,
            card,
            events = listOf(
                SessionEventType.CARD_ANSWERS_UPDATED to mapOf(
                    "cardRevision" to (session.cardRevision + 1),
                    "selectedSignIds" to (request.input.incident?.selectedSignIds ?: emptyList<String>()),
                    "answeredQuestionIds" to (request.input.incident?.answers?.map { it.questionId } ?: emptyList<String>())
                ),
                SessionEventType.ROUTING_CALCULATED to routingEventPayload(session.cardRevision + 1, calculation)
            )
        )
        emitTimeLimitEventOnce(updated)
        return updated.toView()
    }

    /** Отправка на оценку: обязательные поля должны быть заполнены, тип вычислен. */
    @Transactional
    fun submit(sessionId: UUID, request: SubmitCardRequest): SessionReport {
        var session = requireCardSession(sessionId)
        if (request.input.isNotEmpty() && request.input != session.operatorCard.input) {
            saveCard(sessionId, SaveCardRequest(request.input, request.expectedRevision))
            session = requireSession(sessionId)
        }
        validateCard(session)
        emitTimeLimitEventOnce(session)
        sessionService.submitAnswer(session.id)
        serviceAssignments.assignSubmittedCard(session.id)
        session = requireSession(session.id)
        if (session.state == SessionState.ACTIVE) {
            sessionService.complete(session.id)
        }
        session = requireSession(session.id)
        if (session.state != SessionState.COMPLETED) {
            throw IllegalStateException("Отправка доступна только для активной или завершённой сессии")
        }
        sessionService.startScoring(session.id)
        session = requireSession(session.id)
        // Оценку считает AI: там рубрика, разбор транскрипта и объяснения.
        // Если он недоступен, занятие не останавливается - Core отдаёт свой
        // упрощённый отчёт, а карточка обучающегося уже сохранена.
        val report = scoreByAi(session) ?: score(session)
        reportRepository.save(report)
        sessionService.completeScoring(session.id)
        return report
    }

    fun report(sessionId: UUID): SessionReport = reportRepository.findBySessionId(sessionId)

    private fun routingEventPayload(cardRevision: Int, calculation: CardCalculation): Map<String, Any?> = mapOf(
        "cardRevision" to cardRevision,
        "status" to calculation.status.name,
        "classifierVersion" to calculation.classifierVersion,
        "classifierCode" to calculation.classifierCode,
        "incidentType" to calculation.incidentType,
        "ekp35IncidentType" to calculation.ekp35IncidentType,
        "responseScenarioCode" to calculation.responseScenarioCode,
        "serviceIds" to calculation.services.map { it.id },
        "missingInputIds" to calculation.missingInputIds
    )

    private fun emitTimeLimitEventOnce(session: TrainingSession) {
        if (session.timeLimitExceeded() && !session.timeLimitEventEmitted) {
            session.markTimeLimitEventEmitted()
            sessionRepository.save(session)
            sessionService.appendEvent(
                session.id,
                SessionEventType.CARD_TIME_LIMIT_EXCEEDED,
                mapOf(
                    "timeLimitSeconds" to session.scenario.timeLimitSeconds,
                    "elapsedSeconds" to session.startedAt?.let { Duration.between(it, java.time.Instant.now()).seconds },
                    "cardRevision" to session.cardRevision
                )
            )
        }
    }

    private fun validateCard(session: TrainingSession) {
        val card = session.operatorCard
        val calculation = card.calculation
        val missing = buildList {
            if (calculation == null || calculation.status != CalculationStatus.RESOLVED) {
                add("incident.selectedSignIds")
            }
            if (card.input.address?.displayAddress.isNullOrBlank()) add("incident.address.displayAddress")
            if (card.input.victims == null) add("victims.present")
            calculation?.missingInputIds?.forEach { add(it) }
        }
        if (missing.isNotEmpty()) {
            throw IllegalArgumentException("Не заполнены обязательные поля карточки: ${missing.joinToString()}")
        }
    }

    /** Просит AI разобрать занятие и переводит его отчёт в модель Core. */
    private fun scoreByAi(session: TrainingSession): SessionReport? {
        val card = session.operatorCard
        val command = ru.sirena112.core.integration.AiScoreCommand(
            sessionId = session.id.toString(),
            scenario = session.scenario,
            submittedCard = card.input,
            calculation = card.calculation,
            elapsedSeconds = elapsedSeconds(session)
        )

        val report = aiClient.score(command) ?: return null

        // Штрафы AI переносим в ошибки: в модели Core отдельного места для них
        // нет, а терять объяснение снятых баллов нельзя.
        val errors = report.errors.map { ScoreError(it.code, it.message, it.field) } +
            report.penalties.map { ScoreError(it.code, it.message, null) }

        return SessionReport(
            sessionId = session.id,
            score = report.totalScore,
            maxScore = report.maxScore,
            passed = report.passed,
            criteria = report.criteria.map { criterion ->
                CriterionScore(
                    code = criterion.code,
                    passed = criterion.status == "PASSED",
                    points = criterion.earnedPoints,
                    maxPoints = criterion.maxPoints,
                    message = criterion.description
                )
            },
            errors = errors,
            recommendations = report.recommendations,
            classifierVersion = report.classifierVersion ?: session.scenario.groundTruth.classifierVersion,
            classifierCode = session.scenario.groundTruth.classifierCode
        )
    }

    /** Сколько заняло занятие: нужно AI для проверки норматива времени. */
    private fun elapsedSeconds(session: TrainingSession): Long? {
        val startedAt = session.startedAt ?: return null
        val endedAt = session.endedAt ?: java.time.Instant.now()
        return java.time.Duration.between(startedAt, endedAt).seconds.coerceAtLeast(0)
    }

    /**
     * Запасная оценка Core на случай недоступного AI: признаки через
     * вычисленный код, службы через совпадение маршрутизации, ответы и адрес -
     * по исходным данным оператора.
     */
    private fun score(session: TrainingSession): SessionReport {
        val card = session.operatorCard
        val truth = session.scenario.groundTruth
        val calculation = card.calculation
        val studentAnswers = card.input.incident?.answers
            ?.associate { it.questionId to it.optionIds } ?: emptyMap()
        val criteria = CardScenarioFixtures.DEFAULT_RUBRIC.map { criterion ->
            val passed = when (criterion.code) {
                "SIGNS" -> truth.matchesCalculation(calculation)
                "ANSWERS" -> truth.expectedAnswers().all { (questionId, options) ->
                    studentAnswers[questionId] == options
                }
                "SERVICES" -> calculation?.status == CalculationStatus.RESOLVED &&
                    calculation.services.map { it.id }.toSet() == truth.expectedServiceIds()
                "ADDRESS" -> !card.input.address?.displayAddress.isNullOrBlank()
                else -> false
            }
            val max = criterion.weight * 100.0
            CriterionScore(
                code = criterion.code,
                passed = passed,
                points = if (passed) max else 0.0,
                maxPoints = max,
                message = if (passed) "Критерий выполнен" else "Значение не совпадает с эталоном"
            )
        }
        val errors = criteria.filterNot { it.passed }.map { criterion ->
            ScoreError(
                code = "CRITERION_${criterion.code}",
                message = criterion.message,
                field = criterion.code.lowercase()
            )
        }
        val maxScore = criteria.sumOf { it.maxPoints }
        val score = criteria.sumOf { it.points }
        return SessionReport(
            sessionId = session.id,
            score = score,
            maxScore = maxScore,
            passed = errors.isEmpty(),
            criteria = criteria,
            errors = errors,
            recommendations = errors.map { "Проверьте поле ${it.field}" },
            classifierVersion = truth.classifierVersion,
            classifierCode = truth.classifierCode
        )
    }

    private fun requireSession(sessionId: UUID): TrainingSession = sessionRepository.findById(sessionId)
        ?: throw NoSuchElementException("Учебная сессия $sessionId не найдена")

    private fun requireCardSession(sessionId: UUID): TrainingSession = requireSession(sessionId).also {
        if (it.mode != SessionMode.CARD) throw IllegalStateException("Карточная операция недоступна для голосовой сессии")
    }

    private fun TrainingSession.toView(): SessionView = SessionView(
        id = id,
        scenarioId = scenario.id,
        mode = mode,
        state = state,
        card = operatorCard,
        cardRevision = cardRevision,
        startedAt = startedAt,
        endedAt = endedAt,
        timeLimitSeconds = scenario.timeLimitSeconds,
        timeLimitExceeded = timeLimitExceeded(),
        report = reportRepository.findBySessionIdOrNull(id)
    )

    companion object {
        /** Сценарий по умолчанию - фикстура 1050602 из каталога контрактов. */
        val DEFAULT_SCENARIO_ID: UUID = UUID.fromString("80c14c89-f2b7-527a-bd6f-268cdc3d4a11")
    }
}

@Configuration
class CardTrainingConfiguration {
    @Bean
    fun classifierCatalog(objectMapper: com.fasterxml.jackson.databind.ObjectMapper): ClassifierCatalog =
        ClassifierCatalog.load(null, objectMapper)

    @Bean
    fun classifierService(catalog: ClassifierCatalog): ClassifierService =
        ClassifierService(catalog, ClassificationEngine(catalog))

    @Bean
    fun cardScenarioFixtures(objectMapper: com.fasterxml.jackson.databind.ObjectMapper): CardScenarioFixtures =
        CardScenarioFixtures(objectMapper)

    @Bean
    @org.springframework.boot.autoconfigure.condition.ConditionalOnProperty(
        name = ["core.storage"], havingValue = "in-memory", matchIfMissing = true
    )
    fun scenarioRepository(
        catalog: ClassifierCatalog,
        fixtures: CardScenarioFixtures
    ): InMemoryScenarioRepository = InMemoryScenarioRepository().also { repository ->
        fixtures.loadAll(catalog.contractsDir().resolve("examples")).forEach(repository::save)
    }

    @Bean
    @org.springframework.boot.autoconfigure.condition.ConditionalOnProperty(
        name = ["core.storage"], havingValue = "in-memory", matchIfMissing = true
    )
    fun trainingSessionRepository(): InMemoryTrainingSessionRepository = InMemoryTrainingSessionRepository()

    @Bean
    @org.springframework.boot.autoconfigure.condition.ConditionalOnProperty(
        name = ["core.storage"], havingValue = "in-memory", matchIfMissing = true
    )
    fun sessionEventRepository(): InMemorySessionEventRepository = InMemorySessionEventRepository()

    @Bean
    @org.springframework.boot.autoconfigure.condition.ConditionalOnProperty(
        name = ["core.storage"], havingValue = "in-memory", matchIfMissing = true
    )
    fun sessionReportRepository(): SessionReportRepository = InMemorySessionReportRepository()

    @Bean
    fun trainingSessionService(
        sessions: TrainingSessionRepository,
        events: SessionEventRepository
    ): TrainingSessionService = TrainingSessionService(sessions, events)
}
