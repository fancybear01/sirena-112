package ru.sirena112.core.domain

import java.util.UUID

/** Группа происшествия из актуального классификатора Системы 112. */
enum class ScenarioCategory {
    FIRE,
    ACCIDENT,
    EXPLOSION,
    EXPLOSION_THREAT,
    COLLAPSE,
    COLLAPSE_THREAT,
    NATURAL_HAZARD,
    ENVIRONMENT,
    HYDRAULIC_FACILITY,
    INDUSTRIAL_ACCIDENT,
    HAZMAT_THREAT,
    TRANSPORT_FACILITY,
    GAS,
    UTILITY,
    PUBLIC_ORDER,
    ROAD_CONDITION,
    PERSON_AT_RISK,
    CHILD_AT_RISK,
    DEATH,
    SOCIAL_AID,
    ANIMAL,
    MEDICAL,
    OTHER
}

typealias Category = ScenarioCategory

enum class Difficulty {
    BASIC,
    INTERMEDIATE,
    ADVANCED
}

data class IncidentSigns(
    val level1: String,
    val level2: String? = null,
    val level3: String? = null,
    val additional: List<String> = emptyList()
) {
    init {
        require(level1.isNotBlank()) { "Признак level1 не может быть пустым" }
        require(additional.all { it.isNotBlank() }) { "Дополнительные признаки не могут быть пустыми" }
        require(additional.size == additional.toSet().size) { "Дополнительные признаки не должны повторяться" }
    }
}

data class GroundTruth(
    val incidentType: String,
    val ekpCode: String? = null,
    val signs: IncidentSigns? = null,
    val address: String? = null,
    val requiredServices: Set<String> = emptySet(),
    val facts: Map<String, Any?> = emptyMap()
) {
    init {
        require(incidentType.isNotBlank()) { "Тип происшествия не может быть пустым" }
        if (ekpCode != null) {
            require(ekpCode.matches(Regex("^[0-9]{6,9}$"))) {
                "Код ЕКП должен содержать от 6 до 9 цифр"
            }
        }
        require(requiredServices.all { it.isNotBlank() }) { "Службы не могут быть пустыми" }
    }
}

data class RubricCriterion(
    val code: String,
    val description: String,
    val weight: Double,
    val critical: Boolean = false
) {
    init {
        require(code.isNotBlank()) { "Код критерия не может быть пустым" }
        require(description.isNotBlank()) { "Описание критерия не может быть пустым" }
        require(weight >= 0) { "Вес критерия не может быть отрицательным" }
    }
}

data class Rubric(val criteria: List<RubricCriterion>) {
    init {
        require(criteria.isNotEmpty()) { "Рубрика должна содержать хотя бы один критерий" }
        require(criteria.map { it.code }.toSet().size == criteria.size) {
            "Коды критериев должны быть уникальными"
        }
    }
}

data class CallerProfile(
    val persona: String? = null,
    val panic: Double? = null,
    val trust: Double? = null,
    val patience: Double? = null,
    val voice: String? = null,
    val background: String? = null
) {
    init {
        listOf(panic, trust, patience).filterNotNull().forEach {
            require(it in 0.0..1.0) { "Параметры профиля абонента должны быть в диапазоне 0..1" }
        }
    }
}

/** Доменная модель сценария, совпадающая с contracts/scenario.schema.json. */
data class Scenario(
    val id: UUID,
    val version: Int,
    val title: String,
    val category: ScenarioCategory,
    val difficulty: Difficulty,
    val profile: String,
    val timeLimitSeconds: Int = 30,
    val groundTruth: GroundTruth,
    val rubric: Rubric,
    val caller: CallerProfile? = null
) {
    init {
        require(version >= 1) { "Версия сценария должна быть не меньше 1" }
        require(title.isNotBlank()) { "Название сценария не может быть пустым" }
        require(profile.isNotBlank()) { "Профиль сценария не может быть пустым" }
        require(timeLimitSeconds > 0) { "Лимит времени должен быть положительным" }
    }

    companion object {
        fun draft(
            title: String,
            category: ScenarioCategory,
            difficulty: Difficulty,
            profile: String,
            groundTruth: GroundTruth,
            rubric: Rubric,
            caller: CallerProfile? = null,
            timeLimitSeconds: Int = 30
        ): Scenario = Scenario(
            id = UUID.randomUUID(),
            version = 1,
            title = title,
            category = category,
            difficulty = difficulty,
            profile = profile,
            timeLimitSeconds = timeLimitSeconds,
            groundTruth = groundTruth,
            rubric = rubric,
            caller = caller
        )
    }
}
