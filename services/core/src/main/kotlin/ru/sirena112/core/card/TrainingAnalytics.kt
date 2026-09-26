package ru.sirena112.core.card

import org.springframework.web.bind.annotation.GetMapping
import org.springframework.web.bind.annotation.RequestMapping
import org.springframework.web.bind.annotation.RestController
import ru.sirena112.core.domain.SessionMode
import ru.sirena112.core.domain.SessionState
import ru.sirena112.core.domain.TrainingSessionRepository
import java.time.LocalDate
import java.time.ZoneOffset

data class ScoreBand(val label: String, val count: Int)
data class IncidentTypeCount(val code: String, val name: String, val count: Int)
data class ErrorCount(val criterionCode: String, val count: Int)
data class DailyCount(val day: LocalDate, val count: Int, val averagePercent: Double)

/** Only aggregate, non-personal data. Empty averages are null, not synthetic zeroes. */
data class TrainingAnalyticsSummary(
    val completedSessions: Int,
    val averagePercent: Double?,
    val medianPercent: Double?,
    val scoreDistribution: List<ScoreBand>,
    val incidentTypes: List<IncidentTypeCount>,
    val topErrors: List<ErrorCount>,
    val daily: List<DailyCount>
)

@RestController
@RequestMapping("/api/teacher/analytics")
class TrainingAnalyticsController(
    private val sessions: TrainingSessionRepository,
    private val reports: SessionReportRepository
) {
    @GetMapping("/summary")
    fun summary(): TrainingAnalyticsSummary {
        val scored = sessions.findAll().asSequence()
            .filter { it.mode == SessionMode.CARD && it.state == SessionState.SCORED && it.endedAt != null }
            .associateBy { it.id }
        val results = reports.findAll().asSequence()
            .mapNotNull { report -> scored[report.sessionId]?.let { it to report } }
            .toList()
        val percentages = results.map { (_, report) -> percent(report) }
        val sorted = percentages.sorted()
        val median = when {
            sorted.isEmpty() -> null
            sorted.size % 2 == 1 -> sorted[sorted.size / 2]
            else -> (sorted[sorted.size / 2 - 1] + sorted[sorted.size / 2]) / 2.0
        }
        val bands = listOf(0 to 20, 20 to 40, 40 to 60, 60 to 80, 80 to 100).mapIndexed { index, (min, max) ->
            ScoreBand(if (index == 0) "0–20" else ">${min}–$max", percentages.count {
                (index == 0 || it > min) && it <= max
            })
        }
        val incidentTypes = results.groupingBy { (session, _) ->
            session.scenario.groundTruth.classifierCode to session.scenario.groundTruth.incidentType
        }.eachCount().entries
            .sortedWith(compareByDescending<Map.Entry<Pair<String, String>, Int>> { it.value }.thenBy { it.key.first })
            .map { (type, count) -> IncidentTypeCount(type.first, type.second, count) }
        val topErrors = results.flatMap { (_, report) ->
            report.criteria.asSequence().filterNot { it.passed }.map { it.code }.distinct().toList()
        }.groupingBy { it }.eachCount().entries
            .sortedWith(compareByDescending<Map.Entry<String, Int>> { it.value }.thenBy { it.key })
            .map { (code, count) -> ErrorCount(code, count) }
        val daily = results.groupBy { (session, _) ->
            session.endedAt!!.atZone(ZoneOffset.UTC).toLocalDate()
        }.toSortedMap().map { (day, entries) ->
            DailyCount(day, entries.size, entries.map { (_, report) -> percent(report) }.average())
        }
        return TrainingAnalyticsSummary(
            results.size,
            percentages.takeIf { it.isNotEmpty() }?.average(),
            median,
            bands,
            incidentTypes,
            topErrors,
            daily
        )
    }

    private fun percent(report: SessionReport): Double =
        if (report.maxScore > 0.0) (report.score / report.maxScore * 100.0).coerceIn(0.0, 100.0) else 0.0
}
