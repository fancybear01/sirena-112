package ru.sirena112.core.card

import org.springframework.stereotype.Service
import ru.sirena112.core.domain.Category
import ru.sirena112.core.domain.Difficulty
import ru.sirena112.core.domain.GroundTruth
import ru.sirena112.core.domain.InMemoryScenarioRepository
import ru.sirena112.core.domain.InMemorySessionEventRepository
import ru.sirena112.core.domain.InMemoryTrainingSessionRepository
import ru.sirena112.core.domain.IncidentSigns
import ru.sirena112.core.domain.OperatorCard
import ru.sirena112.core.domain.Rubric
import ru.sirena112.core.domain.RubricCriterion
import ru.sirena112.core.domain.Scenario
import ru.sirena112.core.domain.ScenarioRepository
import ru.sirena112.core.domain.SessionState
import ru.sirena112.core.domain.SessionMode
import ru.sirena112.core.domain.SessionEventRepository
import ru.sirena112.core.domain.TrainingSession
import ru.sirena112.core.domain.TrainingSessionRepository
import ru.sirena112.core.domain.TrainingSessionService
import java.util.UUID

data class CreateCardSessionRequest(val scenarioId: UUID? = null)

data class SaveCardRequest(
    val incidentType: String? = null,
    val signs: IncidentSigns? = null,
    val address: String? = null,
    val requiredServices: Set<String> = emptySet(),
    val facts: Map<String, Any?> = emptyMap()
) {
    fun toDomain(): OperatorCard = OperatorCard(incidentType, signs, address, requiredServices, facts)
}

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
    val recommendations: List<String>
)

data class SessionView(
    val id: UUID,
    val scenarioId: UUID,
    val mode: SessionMode,
    val state: SessionState,
    val card: OperatorCard,
    val report: SessionReport? = null
)

@Service
class CardTrainingFacade(
    private val scenarioRepository: ScenarioRepository,
    private val sessionRepository: TrainingSessionRepository,
    private val sessionService: TrainingSessionService
) {
    private val reports = java.util.concurrent.ConcurrentHashMap<UUID, SessionReport>()

    fun scenarios(): List<Scenario> = scenarioRepository.findAll()

    fun createSession(request: CreateCardSessionRequest): SessionView {
        val scenario = scenarioRepository.findById(request.scenarioId ?: FIXED_SCENARIO_ID)
            ?: throw NoSuchElementException("Сценарий ${request.scenarioId} не найден")
        return sessionService.create(scenario, SessionMode.CARD).toView()
    }

    fun start(sessionId: UUID): SessionView {
        val session = requireSession(sessionId)
        sessionService.markReady(session.id)
        return sessionService.startCard(session.id).toView()
    }

    fun stop(sessionId: UUID): SessionView = sessionService.complete(sessionId).toView()

    fun get(sessionId: UUID): SessionView = requireSession(sessionId).toView()

    fun saveCard(sessionId: UUID, request: SaveCardRequest): SessionView {
        val card = request.toDomain()
        if (card == OperatorCard()) {
            throw IllegalArgumentException("Карточка должна содержать хотя бы одно заполненное поле")
        }
        return sessionService.updateCard(sessionId, card).toView()
    }

    fun submit(sessionId: UUID): SessionReport {
        val session = requireSession(sessionId)
        validateCard(session)
        sessionService.submitAnswer(session.id)
        if (session.state == SessionState.ACTIVE) {
            sessionService.complete(session.id)
        }
        if (session.state != SessionState.COMPLETED) {
            throw IllegalStateException("Отправка доступна только для активной или завершённой сессии")
        }
        sessionService.startScoring(session.id)
        val report = score(session)
        reports[session.id] = report
        sessionService.completeScoring(session.id)
        return report
    }

    fun report(sessionId: UUID): SessionReport = reports[sessionId]
        ?: throw NoSuchElementException("Отчёт для сессии $sessionId ещё не сформирован")

    private fun validateCard(session: TrainingSession) {
        val card = session.operatorCard
        val missing = buildList {
            if (card.incidentType.isNullOrBlank()) add("incidentType")
            if (card.address.isNullOrBlank()) add("address")
            if (card.requiredServices.isEmpty()) add("requiredServices")
        }
        if (missing.isNotEmpty()) {
            throw IllegalArgumentException("Не заполнены обязательные поля карточки: ${missing.joinToString()}")
        }
    }

    private fun score(session: TrainingSession): SessionReport {
        val card = session.operatorCard
        val truth = session.scenario.groundTruth
        val criteria = session.scenario.rubric.criteria.map { criterion ->
            val passed = when (criterion.code.uppercase()) {
                "INCIDENT_TYPE", "TYPE" -> card.incidentType == truth.incidentType
                "ADDRESS" -> card.address == truth.address
                "SERVICES", "REQUIRED_SERVICES" -> card.requiredServices == truth.requiredServices
                "SIGNS" -> card.signs == truth.signs
                else -> card.facts[criterion.code] == truth.facts[criterion.code]
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
            recommendations = errors.map { "Проверьте поле ${it.field}" }
        )
    }

    private fun requireSession(sessionId: UUID): TrainingSession = sessionRepository.findById(sessionId)
        ?: throw NoSuchElementException("Учебная сессия $sessionId не найдена")

    private fun TrainingSession.toView(): SessionView = SessionView(
        id = id,
        scenarioId = scenario.id,
        mode = mode,
        state = state,
        card = operatorCard,
        report = reports[id]
    )

    companion object {
        val FIXED_SCENARIO_ID: UUID = UUID.fromString("0199d7b6-0000-7000-8000-000000000010")

        fun fixedScenario(): Scenario = Scenario(
            id = FIXED_SCENARIO_ID,
            version = 1,
            title = "Задымление в мусоропроводе жилого дома",
            category = Category.FIRE,
            difficulty = Difficulty.BASIC,
            profile = "Оператор принимает сообщение о задымлении в жилом доме",
            timeLimitSeconds = 60,
            groundTruth = GroundTruth(
                incidentType = "задымление: мусоропровод",
                ekpCode = "1050602",
                signs = IncidentSigns("жилой дом", "мусоропровод", "дым"),
                address = "Москва, ул. Берзарина, д. 21, корп. 1, под. 3",
                requiredServices = setOf("Служба 101", "ДДС района", "МОЭК"),
                facts = mapOf("callerSafe" to true)
            ),
            rubric = Rubric(
                listOf(
                    RubricCriterion("INCIDENT_TYPE", "Тип происшествия", 0.30, critical = true),
                    RubricCriterion("ADDRESS", "Адрес", 0.25),
                    RubricCriterion("SERVICES", "Необходимые службы", 0.25, critical = true),
                    RubricCriterion("SIGNS", "Признаки происшествия", 0.20)
                )
            )
        )
    }
}

@org.springframework.context.annotation.Configuration
class CardTrainingConfiguration {
    @org.springframework.context.annotation.Bean
    fun scenarioRepository(): InMemoryScenarioRepository = InMemoryScenarioRepository().also {
        it.save(CardTrainingFacade.fixedScenario())
    }

    @org.springframework.context.annotation.Bean
    fun trainingSessionRepository(): InMemoryTrainingSessionRepository = InMemoryTrainingSessionRepository()

    @org.springframework.context.annotation.Bean
    fun sessionEventRepository(): InMemorySessionEventRepository = InMemorySessionEventRepository()

    @org.springframework.context.annotation.Bean
    fun trainingSessionService(
        sessions: TrainingSessionRepository,
        events: SessionEventRepository
    ): TrainingSessionService = TrainingSessionService(sessions, events)
}
