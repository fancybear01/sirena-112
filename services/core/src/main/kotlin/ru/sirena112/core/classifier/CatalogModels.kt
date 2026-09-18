package ru.sirena112.core.classifier

import com.fasterxml.jackson.annotation.JsonIgnoreProperties

/**
 * Разбор contracts/catalog/classifier-v046-11.json (схема 1.0.0 из задачи #32).
 * Строгий к неизвестным полям: изменение структуры каталога должно ломать
 * запуск понятной ошибкой, а не молча терять данные.
 */
@JsonIgnoreProperties(ignoreUnknown = true)
data class CatalogFile(
    val schemaVersion: String,
    val classifierVersion: String,
    val services: List<CatalogService>,
    val columns: List<CatalogColumn>,
    val questions: List<CatalogQuestion>,
    val signs: List<CatalogSign>,
    val records: List<CatalogRecord>
)

@JsonIgnoreProperties(ignoreUnknown = true)
data class CatalogService(
    val id: String,
    val displayName: String
)

@JsonIgnoreProperties(ignoreUnknown = true)
data class CatalogColumn(
    val sourceColumn: String,
    val serviceId: String,
    val condition: CatalogCondition,
    val requiresReview: Boolean
)

@JsonIgnoreProperties(ignoreUnknown = true)
data class CatalogCondition(
    val all: List<CatalogConditionTerm> = emptyList()
)

@JsonIgnoreProperties(ignoreUnknown = true)
data class CatalogConditionTerm(
    val questionId: String,
    val equals: Any? = null
) {
    /** Ожидаемое значение после разрешения ответа: Boolean или строка-идентификатор опции. */
    val expected: Any?
        get() = when (equals) {
            is Boolean -> equals
            is String -> equals
            else -> null
        }
}

@JsonIgnoreProperties(ignoreUnknown = true)
data class CatalogQuestion(
    val id: String,
    val label: String,
    val inputType: String,
    val options: List<CatalogOption>,
    val requiresReview: Boolean
)

@JsonIgnoreProperties(ignoreUnknown = true)
data class CatalogOption(
    val id: String,
    val label: String,
    val value: Boolean? = null
)

@JsonIgnoreProperties(ignoreUnknown = true)
data class CatalogSign(
    val id: String,
    val level: Int,
    val label: String,
    val parentId: String?
)

@JsonIgnoreProperties(ignoreUnknown = true)
data class CatalogRecord(
    val classifierCode: String,
    val signIds: List<String?>,
    val questionIds: List<String> = emptyList(),
    val incidentType: String,
    val ekp35IncidentType: String? = null,
    val responseScenarioCode: String? = null,
    val responseScenarioStatus: String,
    val mainServiceIds: List<String> = emptyList(),
    val routingRules: List<CatalogRoutingRule> = emptyList(),
    val section: String? = null,
    val warnings: List<String> = emptyList()
)

@JsonIgnoreProperties(ignoreUnknown = true)
data class CatalogRoutingRule(
    val id: String,
    val column: String,
    val action: String,
    val destinationIncidentType: String? = null,
    val requiresReview: Boolean
)
