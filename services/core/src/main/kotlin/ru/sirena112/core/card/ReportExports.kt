package ru.sirena112.core.card

import org.apache.pdfbox.pdmodel.PDDocument
import org.apache.pdfbox.pdmodel.PDPage
import org.apache.pdfbox.pdmodel.PDPageContentStream
import org.apache.pdfbox.pdmodel.common.PDRectangle
import org.apache.pdfbox.pdmodel.font.PDType0Font
import org.apache.poi.xssf.usermodel.XSSFWorkbook
import org.springframework.http.ContentDisposition
import org.springframework.http.HttpHeaders
import org.springframework.http.MediaType
import org.springframework.http.ResponseEntity
import org.springframework.web.bind.annotation.GetMapping
import org.springframework.web.bind.annotation.PathVariable
import org.springframework.web.bind.annotation.RequestMapping
import org.springframework.web.bind.annotation.RestController
import ru.sirena112.core.classifier.ClassifierCatalog
import ru.sirena112.core.domain.SessionMode
import ru.sirena112.core.domain.SessionState
import ru.sirena112.core.domain.TrainingSessionRepository
import java.io.ByteArrayOutputStream
import java.nio.file.Files
import java.nio.file.Paths
import java.util.UUID

/** One immutable, non-personal snapshot is passed to either renderer. */
data class ExportSnapshot(val title: String, val rows: List<Pair<String, Any>>)

@RestController
@RequestMapping("/api/teacher")
class ReportExports(
    private val sessions: TrainingSessionRepository,
    private val reports: SessionReportRepository,
    private val analytics: TrainingAnalyticsController,
    private val catalog: ClassifierCatalog,
    private val access: ru.sirena112.core.auth.SessionAccess
) {
    @GetMapping("/sessions/{sessionId}/report.xlsx")
    fun reportXlsx(@PathVariable sessionId: UUID): ResponseEntity<ByteArray> =
        download(reportSnapshot(sessionId), "report-$sessionId.xlsx", XLSX, ::xlsx)

    @GetMapping("/sessions/{sessionId}/report.pdf")
    fun reportPdf(@PathVariable sessionId: UUID): ResponseEntity<ByteArray> =
        download(reportSnapshot(sessionId), "report-$sessionId.pdf", MediaType.APPLICATION_PDF, ::pdf)

    @GetMapping("/analytics/summary.xlsx")
    fun summaryXlsx(): ResponseEntity<ByteArray> = download(summarySnapshot(), "training-summary.xlsx", XLSX, ::xlsx)

    @GetMapping("/analytics/summary.pdf")
    fun summaryPdf(): ResponseEntity<ByteArray> = download(summarySnapshot(), "training-summary.pdf", MediaType.APPLICATION_PDF, ::pdf)

    private fun reportSnapshot(sessionId: UUID): ExportSnapshot {
        access.teacherCanRead(sessionId)
        val session = sessions.findById(sessionId) ?: throw NoSuchElementException("Учебная сессия не найдена")
        if (session.mode != SessionMode.CARD || session.state != SessionState.SCORED || session.endedAt == null) {
            throw IllegalStateException("Экспорт доступен только после оценки завершённой карточной сессии")
        }
        val report = reports.findBySessionId(sessionId)
        return ExportSnapshot("Training report", buildList {
            add("Session ID" to report.sessionId.toString())
            add("Classifier version" to (report.classifierVersion ?: session.scenario.groundTruth.classifierVersion))
            add("Classifier code" to (report.classifierCode ?: session.scenario.groundTruth.classifierCode))
            add("Score" to report.score)
            add("Maximum score" to report.maxScore)
            add("Passed" to report.passed.toString())
            report.criteria.forEach { criterion ->
                add("Criterion ${criterion.code} passed" to criterion.passed.toString())
                add("Criterion ${criterion.code} points" to criterion.points)
                add("Criterion ${criterion.code} max" to criterion.maxPoints)
            }
            report.errors.forEachIndexed { index, error -> add("Error ${index + 1} code" to error.code) }
        })
    }

    private fun summarySnapshot(): ExportSnapshot {
        val summary = analytics.summary()
        return ExportSnapshot("Training summary", buildList {
            add("Classifier version" to catalog.classifierVersion)
            add("Scored sessions" to summary.completedSessions)
            summary.averagePercent?.let { add("Average percent" to it) }
            summary.medianPercent?.let { add("Median percent" to it) }
            summary.scoreDistribution.forEach { add("Score band ${it.label}" to it.count) }
            summary.incidentTypes.forEach { add("Incident code ${it.code}" to it.count) }
            summary.topErrors.forEach { add("Failed criterion ${it.criterionCode}" to it.count) }
            summary.daily.forEach { add("Day ${it.day} count" to it.count); add("Day ${it.day} average percent" to it.averagePercent) }
        })
    }

    private fun download(snapshot: ExportSnapshot, filename: String, type: MediaType, render: (ExportSnapshot) -> ByteArray): ResponseEntity<ByteArray> {
        val content = render(snapshot)
        return ResponseEntity.ok()
            .contentType(type)
            .header(HttpHeaders.CONTENT_DISPOSITION, ContentDisposition.attachment().filename(filename).build().toString())
            .contentLength(content.size.toLong())
            .body(content)
    }

    private fun xlsx(snapshot: ExportSnapshot): ByteArray = XSSFWorkbook().use { workbook ->
        val sheet = workbook.createSheet(if (snapshot.title == "Training report") "Report" else "Summary")
        val header = workbook.createCellStyle().also { style ->
            style.setFont(workbook.createFont().also { it.bold = true })
        }
        val title = sheet.createRow(0).createCell(0)
        title.setCellValue(snapshot.title)
        title.cellStyle = header
        val columns = sheet.createRow(1)
        columns.createCell(0).also { it.setCellValue("Metric"); it.cellStyle = header }
        columns.createCell(1).also { it.setCellValue("Value"); it.cellStyle = header }
        snapshot.rows.forEachIndexed { index, (name, value) ->
            val row = sheet.createRow(index + 2)
            row.createCell(0).setCellValue(name)
            val cell = row.createCell(1)
            when (value) {
                is Number -> cell.setCellValue(value.toDouble())
                else -> cell.setCellValue(value.toString())
            }
        }
        sheet.setColumnWidth(0, 42 * 256)
        sheet.setColumnWidth(1, 44 * 256)
        sheet.createFreezePane(0, 2)
        ByteArrayOutputStream().use { output -> workbook.write(output); output.toByteArray() }
    }

    private fun pdf(snapshot: ExportSnapshot): ByteArray = PDDocument().use { document ->
        val fontPath = sequenceOf(
            System.getenv("CORE_EXPORT_FONT_PATH"),
            "C:/Windows/Fonts/arial.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
        ).filterNotNull().map(Paths::get).firstOrNull(Files::isRegularFile)
            ?: throw IllegalStateException("Для PDF нужен TTF-шрифт: задайте CORE_EXPORT_FONT_PATH")
        val font = PDType0Font.load(document, fontPath.toFile())
        var page = PDPage(PDRectangle.A4)
        document.addPage(page)
        var content = PDPageContentStream(document, page)
        var y = page.mediaBox.height - 50f

        fun line(value: String, size: Float, indent: Float = 50f) {
            val text = value.replace(Regex("\\p{Cntrl}"), " ")
            val maxWidth = page.mediaBox.width - indent - 45f
            var current = ""
            fun writeCurrent() {
                if (current.isEmpty()) return
                if (y < 48f) {
                    content.close()
                    page = PDPage(PDRectangle.A4)
                    document.addPage(page)
                    content = PDPageContentStream(document, page)
                    y = page.mediaBox.height - 50f
                }
                content.beginText()
                content.setFont(font, size)
                content.newLineAtOffset(indent, y)
                content.showText(current)
                content.endText()
                y -= size + 7f
                current = ""
            }
            text.forEach { character ->
                val candidate = current + character
                if (font.getStringWidth(candidate) / 1000f * size > maxWidth && current.isNotEmpty()) writeCurrent()
                current += character
            }
            writeCurrent()
        }

        line(snapshot.title, 16f)
        y -= 10f
        snapshot.rows.forEach { (name, value) -> line("$name: $value", 10f) }
        content.close()
        ByteArrayOutputStream().use { output -> document.save(output); output.toByteArray() }
    }

    companion object {
        private val XLSX = MediaType.parseMediaType("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    }
}
