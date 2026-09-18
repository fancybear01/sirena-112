package ru.sirena112.core.classifier

import com.fasterxml.jackson.annotation.JsonIgnoreProperties
import com.fasterxml.jackson.databind.ObjectMapper
import ru.sirena112.core.domain.Difficulty
import ru.sirena112.core.domain.GroundTruth
import ru.sirena112.core.domain.Rubric
import ru.sirena112.core.domain.RubricCriterion
import ru.sirena112.core.domain.Scenario
import ru.sirena112.core.domain.ScenarioCategory
import java.nio.file.Files
import java.nio.file.Path
import java.util.UUID

/**
 * Учебные сценарии загружаются из contracts/examples/scenario-*.json - файлов,
 * сгенерированных из каталога классификатора (задача #32). Списки служб в
 * эталоне вычислены импортёром по routing rules, а не заданы вручную.
 */
class CardScenarioFixtures(private val objectMapper: ObjectMapper) {

    @JsonIgnoreProperties(ignoreUnknown = true)
    private data class FixtureFile(
        val id: UUID,
        val version: Int,
        val title: String,
        val category: String,
        val difficulty: String,
        val profile: String,
        val timeLimitSeconds: Int = 30,
        val groundTruth: FixtureGroundTruth,
        val rubric: FixtureRubric
    )

    @JsonIgnoreProperties(ignoreUnknown = true)
    private data class FixtureGroundTruth(
        val classifierVersion: String,
        val classifierCode: String,
        val incidentType: String,
        val ekp35IncidentType: String?,
        val responseScenarioCode: String?,
        val responseScenarioStatus: String,
        val mainServices: List<FixtureServiceRef>,
        val requiredServices: List<FixtureRoutedService>,
        val expectedInput: OperatorCardInput
    )

    @JsonIgnoreProperties(ignoreUnknown = true)
    private data class FixtureServiceRef(val id: String, val displayName: String)

    @JsonIgnoreProperties(ignoreUnknown = true)
    private data class FixtureRoutedService(
        val id: String,
        val displayName: String,
        val reasons: List<FixtureReason>
    )

    @JsonIgnoreProperties(ignoreUnknown = true)
    private data class FixtureReason(
        val ruleId: String,
        val message: String,
        val matchedInputIds: List<String> = emptyList()
    )

    @JsonIgnoreProperties(ignoreUnknown = true)
    private data class FixtureRubric(val criteria: List<FixtureCriterion> = emptyList())

    @JsonIgnoreProperties(ignoreUnknown = true)
    private data class FixtureCriterion(
        val code: String,
        val description: String? = null,
        val weight: Double = 0.0,
        val critical: Boolean = false
    )

    /** Загружает все сценарии из каталога examples; пустой результат - ошибка запуска. */
    fun loadAll(examplesDir: Path): List<Scenario> {
        require(Files.isDirectory(examplesDir)) { "Каталог примеров не найден: $examplesDir" }
        val files = Files.list(examplesDir).use { stream ->
            stream.collect(java.util.stream.Collectors.toList<Path>())
        }.filter {
            it.fileName.toString().startsWith("scenario-") && it.fileName.toString().endsWith(".json")
        }.sorted()
        val scenarios = files.map { load(it) }
        require(scenarios.isNotEmpty()) { "В $examplesDir нет учебных сценариев" }
        return scenarios
    }

    fun load(file: Path): Scenario {
        val fixture = objectMapper.readValue(file.toFile(), FixtureFile::class.java)
        val truth = GroundTruth(
            classifierVersion = fixture.groundTruth.classifierVersion,
            classifierCode = fixture.groundTruth.classifierCode,
            incidentType = fixture.groundTruth.incidentType,
            ekp35IncidentType = fixture.groundTruth.ekp35IncidentType,
            responseScenarioCode = fixture.groundTruth.responseScenarioCode,
            responseScenarioStatus = ResponseScenarioStatus.valueOf(fixture.groundTruth.responseScenarioStatus),
            mainServices = fixture.groundTruth.mainServices.map { ServiceRef(it.id, it.displayName) },
            requiredServices = fixture.groundTruth.requiredServices.map { service ->
                RoutedService(
                    id = service.id,
                    displayName = service.displayName,
                    reasons = service.reasons.map { reason ->
                        RoutingReason(reason.ruleId, reason.message, reason.matchedInputIds)
                    }
                )
            },
            expectedInput = fixture.groundTruth.expectedInput
        )
        return Scenario(
            id = fixture.id,
            version = fixture.version,
            title = fixture.title,
            category = fixture.category.let { value ->
                ScenarioCategory.values().firstOrNull { it.name == value } ?: ScenarioCategory.OTHER
            },
            difficulty = fixture.difficulty.let { value ->
                Difficulty.values().firstOrNull { it.name == value } ?: Difficulty.BASIC
            },
            profile = fixture.profile,
            timeLimitSeconds = fixture.timeLimitSeconds,
            groundTruth = truth,
            rubric = Rubric(
                fixture.rubric.criteria.map {
                    RubricCriterion(it.code, it.description ?: it.code, it.weight, it.critical)
                }.ifEmpty { DEFAULT_RUBRIC }
            )
        )
    }

    companion object {
        /** Резервная рубрика, если файл сценария не содержит критериев. */
        val DEFAULT_RUBRIC: List<RubricCriterion> = listOf(
            RubricCriterion("SIGNS", "Признаки происшествия", 0.30, critical = true),
            RubricCriterion("ANSWERS", "Ответы на вопросы маршрутизации", 0.20),
            RubricCriterion("SERVICES", "Направленные службы", 0.30, critical = true),
            RubricCriterion("ADDRESS", "Адрес происшествия", 0.20)
        )
    }
}
