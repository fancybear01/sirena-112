package ru.sirena112.core.classifier

/**
 * Вычисление результата карточки по каталогу: сопоставление пути признаков и
 * применение условных routing rules. Семантика повторяет референсный
 * интерпретатор tools/classifier-import/examples.py (задача #32):
 *  - опровергнутое условие молча пропускает правило;
 *  - неотвеченное условие или requiresReview оставляет правило неразрешённым,
 *    и оно не участвует в маршруте;
 *  - DO_NOT_NOTIFY запрещает службу; одновременное совпадение NOTIFY и
 *    DO_NOT_NOTIFY - конфликт, требующий разбора, а не глобальный запрет;
 *  - неотвеченный вопрос - неизвестное значение, а не false/NONE.
 */
class ClassificationEngine(private val catalog: ClassifierCatalog) {

    /** Выровненный путь выбранных признаков: уровни 1..3 без пропусков. */
    data class SignPath(val level1: String?, val level2: String?, val level3: String?) {
        fun asList(): List<String> = listOfNotNull(level1, level2, level3)
    }

    /** Ответы условий: Boolean для вопросов Да/Нет, идентификатор опции для выбора состояния. */
    fun resolveAnswers(answers: List<QuestionAnswer>): Map<String, Any> {
        val resolved = mutableMapOf<String, Any>()
        for (answer in answers) {
            val question = catalog.questionsById[answer.questionId]
                ?: throw IllegalArgumentException("Неизвестный вопрос: ${answer.questionId}")
            val optionId = answer.optionIds.singleOrNull()
                ?: throw IllegalArgumentException(
                    "Вопрос ${answer.questionId} допускает ровно один вариант ответа"
                )
            val option = question.options.find { it.id == optionId }
                ?: throw IllegalArgumentException(
                    "Вариант $optionId не относится к вопросу ${answer.questionId}"
                )
            resolved[answer.questionId] = option.value ?: option.id
        }
        return resolved
    }

    /**
     * Проверяет цепочку выбранных признаков: каждый следующий уровень должен быть
     * ребёнком предыдущего; комбинировать признаки разных веток нельзя.
     */
    fun alignSignPath(selectedSignIds: List<String>): SignPath {
        if (selectedSignIds.isEmpty()) return SignPath(null, null, null)
        val signs = selectedSignIds.map { signId ->
            catalog.signsById[signId]
                ?: throw IllegalArgumentException("Неизвестный признак: $signId")
        }
        if (signs.map { it.id }.toSet().size != signs.size) {
            throw IllegalArgumentException("Признаки не должны повторяться")
        }
        val byLevel = signs.groupBy { it.level }
        if (byLevel.values.any { it.size > 1 }) {
            throw IllegalArgumentException(
                "Несовместимая комбинация признаков: выбраны разные признаки одного уровня"
            )
        }
        val l1 = byLevel[1]?.singleOrNull()
        val l2 = byLevel[2]?.singleOrNull()
        val l3 = byLevel[3]?.singleOrNull()
        if (l2 != null && (l1 == null || l2.parentId != l1.id)) {
            throw IllegalArgumentException(
                "Несовместимая комбинация признаков: ${l2.label} не является следствием уровня 1"
            )
        }
        if (l3 != null && (l2 == null || l3.parentId != l2.id)) {
            throw IllegalArgumentException(
                "Несовместимая комбинация признаков: ${l3.label} не является следствием уровня 2"
            )
        }
        return SignPath(l1?.id, l2?.id, l3?.id)
    }

    /** Применение условных правил записи к ответам; возвращает службы и неразрешённые правила. */
    data class RoutingResult(
        val services: List<RoutedService>,
        val unresolvedRuleIds: List<String>,
        val conflicts: List<String>,
        val missingQuestionIds: List<String>
    )

    fun evaluateRouting(record: CatalogRecord, answers: Map<String, Any>): RoutingResult {
        val selected = mutableMapOf<String, MutableList<RoutingReason>>()
        val denied = mutableSetOf<String>()
        val unresolved = mutableListOf<String>()
        val missing = sortedSetOf<String>()
        for (rule in record.routingRules) {
            val column = catalog.columnsByLetter[rule.column]
                ?: throw IllegalStateException("Каталог не содержит колонку ${rule.column}")
            val terms = column.condition.all
            val contradicted = terms.any { answers[it.questionId] != null && answers[it.questionId] != it.expected }
            if (contradicted) continue
            val unanswered = terms.filter { it.questionId !in answers }.map { it.questionId }
            if (unanswered.isNotEmpty() || column.requiresReview || rule.requiresReview) {
                missing.addAll(unanswered)
                unresolved.add(rule.id)
                continue
            }
            val serviceId = column.serviceId
            if (rule.action == "DO_NOT_NOTIFY") {
                denied.add(serviceId)
            } else {
                selected.getOrPut(serviceId) { mutableListOf() }.add(
                    RoutingReason(
                        ruleId = rule.id,
                        message = "Колонка ${rule.column}: ${rule.destinationIncidentType ?: serviceId}",
                        matchedInputIds = terms.map { it.questionId }
                    )
                )
            }
        }
        val conflicts = (denied intersect selected.keys).sorted()
        val services = selected.filterKeys { it !in denied }
            .toSortedMap()
            .map { (serviceId, reasons) ->
                val ref = catalog.serviceRef(serviceId)
                    ?: throw IllegalStateException("Каталог не содержит службу $serviceId")
                RoutedService(id = ref.id, displayName = ref.displayName, reasons = reasons.sortedBy { it.ruleId })
            }
        return RoutingResult(
            services = services,
            unresolvedRuleIds = unresolved,
            conflicts = conflicts.map { "CONFLICT:$it" },
            missingQuestionIds = missing.toList()
        )
    }
}
