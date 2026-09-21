package ru.sirena112.core.integration

import com.fasterxml.jackson.annotation.JsonIgnoreProperties
import ru.sirena112.core.classifier.CardCalculation
import ru.sirena112.core.classifier.OperatorCardInput
import ru.sirena112.core.domain.Scenario
import java.util.UUID

/**
 * Контракт оценивания Core -> Python AI.
 *
 * Core отправляет всё, что нужно для разбора занятия: сценарий с эталоном,
 * карточку обучающегося в исходном виде и собственный расчёт классификации.
 * Расчёт обязателен: AI службы не маршрутизирует и без него не может
 * проверить ни состав оповещения, ни код происшествия.
 */
data class AiScoreCommand(
    val sessionId: String,
    val scenario: Scenario,
    val submittedCard: OperatorCardInput,
    val calculation: CardCalculation?,
    val elapsedSeconds: Long?
)

/**
 * Отчёт AI в том виде, в котором он приходит по сети.
 *
 * Неизвестные поля игнорируются намеренно: AI может добавлять в ответ
 * служебные сведения, и из-за них разбор ломаться не должен.
 */
@JsonIgnoreProperties(ignoreUnknown = true)
data class AiScoreReport(
    val sessionId: String,
    val scenarioId: String? = null,
    val classifierVersion: String? = null,
    val totalScore: Double,
    val maxScore: Double,
    val passed: Boolean,
    val criteria: List<AiCriterion> = emptyList(),
    val errors: List<AiError> = emptyList(),
    val penalties: List<AiPenalty> = emptyList(),
    val recommendations: List<String> = emptyList()
)

@JsonIgnoreProperties(ignoreUnknown = true)
data class AiCriterion(
    val code: String,
    val description: String,
    val maxPoints: Double,
    val earnedPoints: Double,
    val status: String
)

@JsonIgnoreProperties(ignoreUnknown = true)
data class AiError(
    val code: String,
    val message: String,
    val kind: String? = null,
    val severity: String? = null,
    val field: String? = null
)

@JsonIgnoreProperties(ignoreUnknown = true)
data class AiPenalty(
    val code: String,
    val message: String,
    val points: Double
)

/** Идентификатор сессии в виде, понятном AI. */
fun UUID.asAiSessionId(): String = toString()
