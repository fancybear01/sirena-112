package ru.sirena112.core.classifier

import com.fasterxml.jackson.annotation.JsonIgnoreProperties

/**
 * Контракт 0.3 (contracts/openapi.yaml): клиент отправляет только исходные
 * данные оператора. Вычисляемые поля (classifierCode, incidentType, службы)
 * в исходных данных запрещены, поэтому разбор строгий к неизвестным полям.
 */
@JsonIgnoreProperties(ignoreUnknown = false)
data class OperatorCardInput(
    val caller: CallerInput? = null,
    val incident: IncidentInput? = null,
    val address: AddressInput? = null,
    val description: String? = null,
    val victims: VictimsInput? = null,
    val facts: Map<String, Any?> = emptyMap()
) {
    // Вспомогательные предикаты, а не данные карточки: без @JsonIgnore Jackson
    // отдаёт их как поля empty и notEmpty, и AI отклоняет запрос целиком -
    // в контракте 0.3 неизвестные поля запрещены.
    @com.fasterxml.jackson.annotation.JsonIgnore
    fun isEmpty(): Boolean = this == OperatorCardInput()

    @com.fasterxml.jackson.annotation.JsonIgnore
    fun isNotEmpty(): Boolean = !isEmpty()
}

@JsonIgnoreProperties(ignoreUnknown = false)
data class CallerInput(
    val phoneNumbers: List<PhoneNumberInput> = emptyList(),
    val fullName: String? = null,
    val status: String? = null,
    val communicationChannel: String? = null,
    val language: String? = null
)

@JsonIgnoreProperties(ignoreUnknown = false)
data class PhoneNumberInput(
    val value: String,
    val kind: String,
    val foreign: Boolean = false
)

@JsonIgnoreProperties(ignoreUnknown = false)
data class IncidentInput(
    val selectedSignIds: List<String> = emptyList(),
    val answers: List<QuestionAnswer> = emptyList()
)

@JsonIgnoreProperties(ignoreUnknown = false)
data class QuestionAnswer(
    val questionId: String,
    val optionIds: List<String> = emptyList(),
    val freeText: String? = null
)

@JsonIgnoreProperties(ignoreUnknown = false)
data class AddressInput(
    val displayAddress: String,
    val region: String? = null,
    val locality: String? = null,
    val street: String? = null,
    val house: String? = null,
    val building: String? = null,
    val apartment: String? = null,
    val description: String? = null,
    val latitude: Double? = null,
    val longitude: Double? = null
)

@JsonIgnoreProperties(ignoreUnknown = false)
data class VictimsInput(
    val present: Boolean,
    val count: Int? = null,
    val threatToPeople: Boolean? = null
)

/** Результат вычисления Core по каталогу; клиент его получить не может. */
enum class CalculationStatus { INCOMPLETE, RESOLVED, NO_MATCH }

enum class ResponseScenarioStatus { CODE, MISSING, EXPLICIT_NONE, SOURCE_LABEL }

data class ServiceRef(
    val id: String,
    val displayName: String
)

data class RoutingReason(
    val ruleId: String,
    val message: String,
    val matchedInputIds: List<String> = emptyList()
)

data class RoutedService(
    val id: String,
    val displayName: String,
    val reasons: List<RoutingReason>
)

data class CardCalculation(
    val status: CalculationStatus,
    val classifierVersion: String,
    val classifierCode: String? = null,
    val incidentType: String? = null,
    val ekp35IncidentType: String? = null,
    val responseScenarioCode: String? = null,
    val responseScenarioStatus: ResponseScenarioStatus? = null,
    val mainServices: List<ServiceRef> = emptyList(),
    val services: List<RoutedService> = emptyList(),
    val missingInputIds: List<String> = emptyList(),
    val explanations: List<String> = emptyList()
)

/** Форма заполнения карточки; зависимости уровней и вопросов считает Core. */
data class CardFormDefinition(
    val classifierVersion: String,
    val signGroups: List<SignGroup>,
    val questions: List<QuestionDefinition>
)

data class SignGroup(
    val id: String,
    val label: String,
    val level: Int,
    val required: Boolean,
    val options: List<SelectionOption>
)

data class QuestionDefinition(
    val id: String,
    val label: String,
    val inputType: String,
    val required: Boolean,
    val options: List<SelectionOption>
)

data class SelectionOption(
    val id: String,
    val label: String
)
