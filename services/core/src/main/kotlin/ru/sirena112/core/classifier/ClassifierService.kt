package ru.sirena112.core.classifier

/**
 * Сервис классификации карточки: проверка исходных данных оператора и
 * вычисление CardCalculation по каталогу. Только Core вычисляет результат;
 * клиентские вычисляемые поля отбрасываются на этапе разбора тела запроса.
 */
class ClassifierService(private val catalog: ClassifierCatalog, private val engine: ClassificationEngine) {

    fun classifierVersion(): String = catalog.classifierVersion

    /** Проверка ответов на вопросы: форматы и принадлежность опций вопросам. */
    fun validateAnswers(input: OperatorCardInput) {
        input.incident?.answers?.forEach { answer ->
            if (answer.optionIds.isEmpty() && answer.freeText.isNullOrBlank()) {
                throw IllegalArgumentException(
                    "Ответ на вопрос ${answer.questionId} должен содержать вариант или текст"
                )
            }
        }
        engine.resolveAnswers(input.incident?.answers ?: emptyList())
    }

    /** Полное вычисление результата карточки по исходным данным оператора. */
    fun calculate(input: OperatorCardInput): CardCalculation {
        validateAnswers(input)
        val path = engine.alignSignPath(input.incident?.selectedSignIds ?: emptyList())
        if (path.level1 == null) {
            return CardCalculation(
                status = CalculationStatus.INCOMPLETE,
                classifierVersion = catalog.classifierVersion,
                missingInputIds = listOf(SIGN_GROUP_LEVEL1),
                explanations = listOf("Не выбрана группа происшествия")
            )
        }
        val exact = catalog.recordsForTriple(path.level1, path.level2, path.level3)
        val record = when {
            exact.size == 1 -> exact.single()
            exact.size > 1 -> return CardCalculation(
                status = CalculationStatus.NO_MATCH,
                classifierVersion = catalog.classifierVersion,
                explanations = listOf(
                    "Выбранным признакам соответствует несколько записей классификатора " +
                        "(${exact.size} записей, например ${exact.take(3).map { it.classifierCode }}); " +
                        "требуется уточнение по дополнительным признакам"
                )
            )
            else -> null
        }
        if (record == null) {
            val continuing = catalog.recordsContinuingPrefix(path.level1, path.level2)
            if (continuing.isNotEmpty() && path.level3 == null) {
                val missingGroup = if (path.level2 == null) SIGN_GROUP_LEVEL2 else SIGN_GROUP_LEVEL3
                return CardCalculation(
                    status = CalculationStatus.INCOMPLETE,
                    classifierVersion = catalog.classifierVersion,
                    missingInputIds = listOf(missingGroup),
                    explanations = listOf("Путь признаков не завершён: доступно уточнение уровня")
                )
            }
            return CardCalculation(
                status = CalculationStatus.NO_MATCH,
                classifierVersion = catalog.classifierVersion,
                explanations = listOf("Комбинация признаков не найдена в классификаторе")
            )
        }

        val answers = engine.resolveAnswers(input.incident?.answers ?: emptyList())
        val routing = engine.evaluateRouting(record, answers)
        val mainServices = record.mainServiceIds.mapNotNull { catalog.serviceRef(it) }
        val explanations = buildList {
            add("Совпадение с записью классификатора ${record.classifierCode} (${record.incidentType})")
            routing.unresolvedRuleIds.forEach { ruleId ->
                add("Правило $ruleId не применено: неотвеченное условие или требуется методическая проверка")
            }
            routing.conflicts.forEach { conflict ->
                add("Конфликт правил для $conflict: совпали разрешающее и запрещающее правила")
            }
            if (record.warnings.isNotEmpty()) {
                add("Запись содержит предупреждения импорта: ${record.warnings.joinToString()}")
            }
        }
        return CardCalculation(
            status = CalculationStatus.RESOLVED,
            classifierVersion = catalog.classifierVersion,
            classifierCode = record.classifierCode,
            incidentType = record.incidentType,
            ekp35IncidentType = record.ekp35IncidentType,
            responseScenarioCode = record.responseScenarioCode,
            responseScenarioStatus = parseScenarioStatus(record.responseScenarioStatus),
            mainServices = mainServices,
            services = routing.services,
            missingInputIds = routing.missingQuestionIds,
            explanations = explanations
        )
    }

    /**
     * Форма для текущего черновика: допустимые следующие признаки зависят от
     * выбранного родителя, вопросы - от записей, продолжающих выбранный путь.
     */
    fun buildForm(input: OperatorCardInput): CardFormDefinition {
        val path = engine.alignSignPath(input.incident?.selectedSignIds ?: emptyList())
        val level1Options = catalog.topLevelSigns()
        val level2Options = path.level1?.let { catalog.childrenOf(it) } ?: emptyList()
        val level3Options = path.level2?.let { catalog.childrenOf(it) } ?: emptyList()
        val relevantRecords = catalog.recordsForTriple(path.level1, path.level2, path.level3)
            .ifEmpty { catalog.recordsContinuingPrefix(path.level1, path.level2) }
        val questions = relevantRecords
            .flatMap { catalog.recordQuestionDefinitions(it) }
            .distinctBy { it.id }
            .sortedBy { it.id }
            .map { q ->
                QuestionDefinition(
                    id = q.id,
                    label = q.label,
                    inputType = q.inputType,
                    required = false,
                    options = q.options.map { SelectionOption(it.id, it.label) }
                )
            }
        return CardFormDefinition(
            classifierVersion = catalog.classifierVersion,
            signGroups = listOf(
                SignGroup(SIGN_GROUP_LEVEL1, "Группа происшествия", 1, true, level1Options.map { SelectionOption(it.id, it.label) }),
                SignGroup(SIGN_GROUP_LEVEL2, "Признак происшествия", 2, false, level2Options.map { SelectionOption(it.id, it.label) }),
                SignGroup(SIGN_GROUP_LEVEL3, "Уточнение признака", 3, false, level3Options.map { SelectionOption(it.id, it.label) })
            ),
            questions = questions
        )
    }

    private fun parseScenarioStatus(value: String): ResponseScenarioStatus = when (value) {
        "CODE" -> ResponseScenarioStatus.CODE
        "MISSING" -> ResponseScenarioStatus.MISSING
        "EXPLICIT_NONE" -> ResponseScenarioStatus.EXPLICIT_NONE
        "SOURCE_LABEL" -> ResponseScenarioStatus.SOURCE_LABEL
        else -> throw IllegalStateException("Неизвестный статус сценария реагирования: $value")
    }

    companion object {
        const val SIGN_GROUP_LEVEL1 = "signs.level1"
        const val SIGN_GROUP_LEVEL2 = "signs.level2"
        const val SIGN_GROUP_LEVEL3 = "signs.level3"
    }
}
