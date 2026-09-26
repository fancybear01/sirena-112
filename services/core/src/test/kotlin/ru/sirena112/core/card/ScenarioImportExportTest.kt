package ru.sirena112.core.card

import com.fasterxml.jackson.databind.JsonNode
import com.fasterxml.jackson.databind.ObjectMapper
import com.fasterxml.jackson.databind.node.ObjectNode
import org.apache.pdfbox.pdmodel.PDDocument
import org.apache.pdfbox.text.PDFTextStripper
import org.apache.poi.xssf.usermodel.XSSFWorkbook
import org.assertj.core.api.Assertions.assertThat
import org.junit.jupiter.api.Test
import org.springframework.beans.factory.annotation.Autowired
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc
import org.springframework.boot.test.context.SpringBootTest
import org.springframework.http.MediaType
import org.springframework.test.annotation.DirtiesContext
import org.springframework.test.web.servlet.MockMvc
import org.springframework.test.web.servlet.get
import org.springframework.test.web.servlet.post
import ru.sirena112.core.domain.OperatorCard
import ru.sirena112.core.domain.ScenarioRepository
import ru.sirena112.core.domain.SessionMode
import ru.sirena112.core.domain.SessionState
import ru.sirena112.core.domain.TrainingSession
import ru.sirena112.core.domain.TrainingSessionRepository
import java.io.ByteArrayInputStream
import java.nio.file.Files
import java.nio.file.Paths
import java.time.Instant
import java.util.UUID

@SpringBootTest(properties = ["core.scenario-import.enabled=true"])
@AutoConfigureMockMvc
@DirtiesContext(classMode = DirtiesContext.ClassMode.BEFORE_CLASS)
class ScenarioImportExportTest {
    @Autowired lateinit var mvc: MockMvc
    @Autowired lateinit var mapper: ObjectMapper
    @Autowired lateinit var scenarios: ScenarioRepository
    @Autowired lateinit var sessions: TrainingSessionRepository
    @Autowired lateinit var reports: SessionReportRepository

    private fun fixture(id: UUID = UUID.randomUUID()): ObjectNode {
        var root = Paths.get("").toAbsolutePath()
        repeat(8) {
            if (Files.isRegularFile(root.resolve("contracts/examples/scenario-1050602.json"))) return@repeat
            root = root.parent ?: return@repeat
        }
        return (mapper.readTree(root.resolve("contracts/examples/scenario-1050602.json").toFile()) as ObjectNode)
            .also { it.put("id", id.toString()); it.put("title", "Imported 1050602") }
    }

    private fun packageBody(vararg items: JsonNode): String = mapper.writeValueAsString(mapOf("scenarios" to items.toList()))

    @Test
    fun `import validates whole package and rejects duplicates without mutation`() {
        val valid = fixture()
        val id = UUID.fromString(valid["id"].asText())
        val preview = mvc.post("/api/teacher/scenarios/import/validate") {
            contentType = MediaType.APPLICATION_JSON
            content = packageBody(valid)
        }.andExpect { status { isOk() } }.andReturn().response.contentAsString
        assertThat(mapper.readTree(preview)["valid"].asBoolean()).isTrue()
        assertThat(scenarios.findById(id)).isNull()

        val wrongVersion = fixture().also { (it["groundTruth"] as ObjectNode).put("classifierVersion", "unrelated") }
        val versionPreview = mvc.post("/api/teacher/scenarios/import/validate") {
            contentType = MediaType.APPLICATION_JSON
            content = packageBody(wrongVersion)
        }.andExpect { status { isOk() } }.andReturn().response.contentAsString
        assertThat(versionPreview).contains("CATALOG_VERSION")
        val duplicatePreview = mvc.post("/api/teacher/scenarios/import/validate") {
            contentType = MediaType.APPLICATION_JSON
            content = packageBody(valid, valid)
        }.andExpect { status { isOk() } }.andReturn().response.contentAsString
        assertThat(duplicatePreview).contains("DUPLICATE_ID")

        val bad = fixture()
        (bad["groundTruth"]["requiredServices"] as com.fasterxml.jackson.databind.node.ArrayNode)
            .add(mapper.readTree("""{"id":"FORGED","displayName":"Forged","reasons":[{"ruleId":"x","message":"x"}]}"""))
        val combined = mvc.post("/api/teacher/scenarios/import/validate") {
            contentType = MediaType.APPLICATION_JSON
            content = packageBody(valid, bad)
        }.andExpect { status { isOk() } }.andReturn().response.contentAsString
        assertThat(mapper.readTree(combined)["valid"].asBoolean()).isFalse()
        mvc.post("/api/teacher/scenarios/import") {
            contentType = MediaType.APPLICATION_JSON
            content = packageBody(valid, bad)
        }.andExpect { status { isBadRequest() } }
        assertThat(scenarios.findById(id)).isNull()

        mvc.post("/api/teacher/scenarios/import") {
            contentType = MediaType.APPLICATION_JSON
            content = packageBody(valid)
        }.andExpect { status { isCreated() } }
        assertThat(scenarios.findById(id)).isNotNull()
        mvc.get("/api/teacher/scenarios")
            .andExpect { status { isOk() } }
            .andReturn().response.contentAsString.also { assertThat(it).contains(id.toString()) }
        mvc.post("/api/teacher/scenarios/import") {
            contentType = MediaType.APPLICATION_JSON
            content = packageBody(valid)
        }.andExpect { status { isConflict() } }
        mvc.post("/api/teacher/scenarios/import/validate") {
            contentType = MediaType.APPLICATION_JSON
            content = packageBody(fixture())
            with { it.remoteAddr = "192.0.2.1"; it }
        }.andExpect { status { isForbidden() } }
    }

    @Test
    fun `exports use real scored report and omit personal text`() {
        val scenario = scenarios.findAll().first()
        val id = UUID.randomUUID()
        val ended = Instant.parse("2026-09-26T10:00:00Z")
        sessions.save(TrainingSession.restore(
            id, scenario, SessionMode.CARD, SessionState.SCORED, OperatorCard(), 0,
            ended.minusSeconds(600), ended.minusSeconds(300), ended, ended, null, false
        ))
        reports.save(SessionReport(
            id, 75.0, 100.0, false,
            listOf(CriterionScore("ADDRESS", false, 0.0, 25.0, "PRIVATE DETAILS")),
            listOf(ScoreError("CRITERION_ADDRESS", "PRIVATE PHONE 123")),
            listOf("PRIVATE RECOMMENDATION"),
            scenario.groundTruth.classifierVersion, scenario.groundTruth.classifierCode
        ))
        val xlsx = mvc.get("/api/teacher/sessions/$id/report.xlsx")
            .andExpect { status { isOk() } }.andReturn().response.contentAsByteArray
        XSSFWorkbook(ByteArrayInputStream(xlsx)).use { workbook ->
            val sheet = workbook.getSheet("Report")
            assertThat(sheet.getRow(2).getCell(1).stringCellValue).isEqualTo(id.toString())
            assertThat(sheet.getRow(5).getCell(1).numericCellValue).isEqualTo(75.0)
            assertThat((0..sheet.lastRowNum).joinToString { row ->
                sheet.getRow(row)?.let { r -> "${r.getCell(0)} ${r.getCell(1)}" } ?: ""
            }).doesNotContain("PRIVATE")
        }
        val pdf = mvc.get("/api/teacher/sessions/$id/report.pdf")
            .andExpect { status { isOk() } }.andReturn().response.contentAsByteArray
        PDDocument.load(pdf).use { document ->
            assertThat(document.numberOfPages).isGreaterThanOrEqualTo(1)
            val text = PDFTextStripper().getText(document)
            assertThat(text).contains(id.toString(), "75.0", "CRITERION_ADDRESS")
            assertThat(text).doesNotContain("PRIVATE")
        }
        val summaryXlsx = mvc.get("/api/teacher/analytics/summary.xlsx")
            .andExpect { status { isOk() } }.andReturn().response.contentAsByteArray
        XSSFWorkbook(ByteArrayInputStream(summaryXlsx)).use { workbook ->
            assertThat(workbook.getSheet("Summary").getRow(3).getCell(1).numericCellValue).isGreaterThanOrEqualTo(1.0)
        }
        val summaryPdf = mvc.get("/api/teacher/analytics/summary.pdf")
            .andExpect { status { isOk() } }.andReturn().response.contentAsByteArray
        PDDocument.load(summaryPdf).use { document ->
            assertThat(PDFTextStripper().getText(document)).contains("Scored sessions")
        }
    }

    @Test
    fun `report export requires existing completed score`() {
        val id = UUID.randomUUID()
        mvc.get("/api/teacher/sessions/$id/report.xlsx").andExpect { status { isNotFound() } }
        val scenario = scenarios.findAll().first()
        val ended = Instant.parse("2026-09-26T10:00:00Z")
        sessions.save(TrainingSession.restore(id, scenario, SessionMode.CARD, SessionState.COMPLETED,
            OperatorCard(), 0, ended.minusSeconds(10), ended.minusSeconds(5), ended, ended, null, false))
        mvc.get("/api/teacher/sessions/$id/report.pdf").andExpect { status { isConflict() } }
        sessions.save(TrainingSession.restore(id, scenario, SessionMode.CARD, SessionState.SCORED,
            OperatorCard(), 0, ended.minusSeconds(10), ended.minusSeconds(5), ended, ended, null, false))
        mvc.get("/api/teacher/sessions/$id/report.xlsx").andExpect { status { isNotFound() } }
    }
}

@SpringBootTest
@AutoConfigureMockMvc
class ScenarioImportDisabledTest {
    @Autowired lateinit var mvc: MockMvc

    @Test
    fun `import is disabled by default`() {
        mvc.post("/api/teacher/scenarios/import/validate") {
            contentType = MediaType.APPLICATION_JSON
            content = """{"scenarios":[]}"""
        }.andExpect { status { isForbidden() } }
    }
}
