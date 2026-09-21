package ru.sirena112.core.classifier

import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Assertions.assertThrows
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test

/**
 * Юнит-тесты движка классификации против реального каталога #32 и
 * золотого эталона 1050602, сгенерированного референсным интерпретатором.
 */
class ClassificationEngineTest {

    private val catalog = ContractTestSupport.catalog()
    private val engine = ClassificationEngine(catalog)
    private val service = ClassifierService(catalog, engine)

    private val signs1050602 = listOf(
        "sign.68eaae1dc9472ce9",
        "sign.8795ab4a7bb0d66a",
        "sign.8b0cf230ebb8ba99"
    )

    private fun input(vararg answers: Pair<String, String>, signs: List<String> = signs1050602): OperatorCardInput {
        val expected = ContractTestSupport.fixtureNode("scenario-1050602.json")
            .at("/groundTruth/expectedInput")
        val base = ContractTestSupport.objectMapper.convertValue(expected, OperatorCardInput::class.java)
        if (answers.isEmpty() && signs == signs1050602) return base
        val override = answers.toMap()
        return base.copy(
            incident = (base.incident ?: IncidentInput()).copy(
                selectedSignIds = signs,
                answers = base.incident!!.answers.map { answer ->
                    if (override.containsKey(answer.questionId)) {
                        answer.copy(optionIds = listOf(override.getValue(answer.questionId)))
                    } else answer
                }
            )
        )
    }

    @Test
    fun `golden row 1050602 reproduces the catalog fixture`() {
        val fixture = ContractTestSupport.fixtureNode("scenario-1050602.json")
        val calculation = service.calculate(input())

        assertEquals(CalculationStatus.RESOLVED, calculation.status)
        assertEquals("1050602", calculation.classifierCode)
        assertEquals("задымление: мусоропровод", calculation.incidentType)
        assertEquals("пожар: мусоропровод", calculation.ekp35IncidentType)
        assertEquals("1_9", calculation.responseScenarioCode)
        assertEquals(ResponseScenarioStatus.CODE, calculation.responseScenarioStatus)
        assertTrue(calculation.missingInputIds.isEmpty()) { "unanswered questions: ${calculation.missingInputIds}" }

        val fixtureMain = fixture.at("/groundTruth/mainServices")
        assertEquals(fixtureMain.size(), calculation.mainServices.size)
        calculation.mainServices.forEachIndexed { i, ref ->
            assertEquals(fixtureMain[i].get("id").asText(), ref.id)
            assertEquals(fixtureMain[i].get("displayName").asText(), ref.displayName)
        }

        val fixtureServices = fixture.at("/groundTruth/requiredServices")
        assertEquals(fixtureServices.size(), calculation.services.size)
        calculation.services.forEachIndexed { i, routed ->
            assertEquals(fixtureServices[i].get("id").asText(), routed.id)
            assertEquals(fixtureServices[i].get("displayName").asText(), routed.displayName)
            val fixtureReasons = fixtureServices[i].get("reasons")
            assertEquals(fixtureReasons.size(), routed.reasons.size)
            routed.reasons.forEachIndexed { j, reason ->
                assertEquals(fixtureReasons[j].get("ruleId").asText(), reason.ruleId)
                assertEquals(fixtureReasons[j].get("message").asText(), reason.message)
                assertEquals(
                    fixtureReasons[j].get("matchedInputIds").map { it.asText() },
                    reason.matchedInputIds
                )
            }
        }
    }

    @Test
    fun `conditional ambulance appears only when victims are present`() {
        val withVictims = service.calculate(input("routing.victims-status" to "PRESENT"))
        assertTrue(
            withVictims.services.any { it.id == "AMBULANCE" },
            "AMBULANCE must be routed when victims are present"
        )

        val withoutVictims = service.calculate(input())
        assertFalse(withoutVictims.services.any { it.id == "AMBULANCE" })

        val notOnScene = service.calculate(input("routing.victims-status" to "NOT_ON_SCENE"))
        assertFalse(notOnScene.services.any { it.id == "AMBULANCE" })
    }

    @Test
    fun `unanswered question is unknown value and blocks its rules`() {
        val base = input()
        val withoutVictimsAnswer = base.copy(
            incident = base.incident!!.copy(
                answers = base.incident!!.answers.filterNot { it.questionId == "routing.victims-status" }
            )
        )
        val calculation = service.calculate(withoutVictimsAnswer)

        assertEquals(CalculationStatus.RESOLVED, calculation.status)
        assertTrue("routing.victims-status" in calculation.missingInputIds)
        assertFalse(calculation.services.any { it.id == "AMBULANCE" })
        assertTrue(calculation.explanations.any { it.startsWith("Правило classifier.") })
    }

    @Test
    fun `ambiguous requiresReview rule cannot silently route`() {
        val calculation = service.calculate(input("routing.culture-listed-facility" to "YES"))

        assertEquals(CalculationStatus.RESOLVED, calculation.status)
        assertFalse(calculation.services.any { it.id == "DEP_CULTURE" })
        assertTrue(calculation.explanations.any { it.contains("classifier.1050602.CE") })
    }

    @Test
    fun `incomplete sign path does not produce a final type`() {
        val calculation = service.calculate(input(signs = listOf("sign.68eaae1dc9472ce9")))

        assertEquals(CalculationStatus.INCOMPLETE, calculation.status)
        assertNull(calculation.classifierCode)
        assertNull(calculation.incidentType)
        assertTrue(calculation.services.isEmpty())
        assertEquals(listOf(ClassifierService.SIGN_GROUP_LEVEL2), calculation.missingInputIds)
    }

    @Test
    fun `two-level path resolves records without the third level`() {
        // Код 2010000 (ДТП): полный путь из двух уровней, третий отсутствует в каталоге.
        val fixture2010000 = ContractTestSupport.fixtureNode("scenario-2010000.json")
        val input2010000 = ContractTestSupport.objectMapper.convertValue(
            fixture2010000.at("/groundTruth/expectedInput"),
            OperatorCardInput::class.java
        )
        val calculation = service.calculate(input2010000)

        assertEquals(CalculationStatus.RESOLVED, calculation.status)
        assertEquals("2010000", calculation.classifierCode)
        assertEquals(
            fixture2010000.at("/groundTruth/requiredServices").map { it.get("id").asText() },
            calculation.services.map { it.id }
        )
    }

    @Test
    fun `ambiguous multi-record group is not resolved silently`() {
        val calculation = service.calculate(input(signs = listOf("sign.5ec12b23acc6b0d7")))

        assertEquals(CalculationStatus.NO_MATCH, calculation.status)
        assertNull(calculation.classifierCode)
        assertTrue(calculation.explanations.single().contains("несколько записей"))
    }

    @Test
    fun `incompatible sign combination is rejected`() {
        // Уровень 2 без родителя уровня 1 - несовместимая комбинация.
        assertThrows(IllegalArgumentException::class.java) {
            service.calculate(input(signs = listOf("sign.8795ab4a7bb0d66a")))
        }
        // Признак уровня 2 из чужой ветки уровня 1.
        val otherLevel1 = catalog.topLevelSigns().first { it.id != "sign.68eaae1dc9472ce9" }
        val otherChild = catalog.childrenOf(otherLevel1.id).firstOrNull()
        if (otherChild != null) {
            assertThrows(IllegalArgumentException::class.java) {
                service.calculate(
                    input(signs = listOf("sign.68eaae1dc9472ce9", otherChild.id))
                )
            }
        }
    }

    @Test
    fun `unknown sign or answer option is rejected with a clear error`() {
        assertThrows(IllegalArgumentException::class.java) {
            service.calculate(input(signs = listOf("sign.unknown")))
        }
        val base = input()
        val badOption = base.copy(
            incident = base.incident!!.copy(
                answers = base.incident!!.answers +
                    QuestionAnswer(questionId = "routing.no-access", optionIds = listOf("MAYBE"))
            )
        )
        assertThrows(IllegalArgumentException::class.java) { service.calculate(badOption) }
    }

    @Test
    fun `card form follows the draft dependencies`() {
        val emptyForm = service.buildForm(OperatorCardInput())

        assertEquals(catalog.classifierVersion, emptyForm.classifierVersion)
        assertEquals(3, emptyForm.signGroups.size)
        assertTrue(emptyForm.signGroups[0].options.isNotEmpty())
        assertTrue(emptyForm.signGroups[1].options.isEmpty())
        assertTrue(emptyForm.questions.isEmpty())

        val afterLevel1 = service.buildForm(
            OperatorCardInput(incident = IncidentInput(selectedSignIds = listOf("sign.68eaae1dc9472ce9")))
        )
        assertTrue(afterLevel1.signGroups[1].options.isNotEmpty())
        assertEquals(
            catalog.childrenOf("sign.68eaae1dc9472ce9").map { it.id }.toSet(),
            afterLevel1.signGroups[1].options.map { it.id }.toSet()
        )
        assertTrue(afterLevel1.questions.isNotEmpty())
        assertTrue(afterLevel1.questions.all { it.inputType == "SINGLE_SELECT" })
    }
}
