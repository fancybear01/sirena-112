package ru.sirena112.core.card

import com.fasterxml.jackson.databind.JsonNode
import com.fasterxml.jackson.databind.ObjectMapper
import com.networknt.schema.JsonSchemaFactory
import com.networknt.schema.SpecVersion
import org.springframework.beans.factory.annotation.Value
import org.springframework.dao.DuplicateKeyException
import org.springframework.http.HttpStatus
import org.springframework.transaction.annotation.Transactional
import org.springframework.web.bind.annotation.PostMapping
import org.springframework.web.bind.annotation.RequestBody
import org.springframework.web.bind.annotation.RequestMapping
import org.springframework.web.bind.annotation.ResponseStatus
import org.springframework.web.bind.annotation.RestController
import ru.sirena112.core.classifier.CalculationStatus
import ru.sirena112.core.classifier.ClassifierCatalog
import ru.sirena112.core.classifier.ClassifierService
import ru.sirena112.core.domain.Scenario
import ru.sirena112.core.domain.ScenarioRepository
import javax.servlet.http.HttpServletRequest
import java.util.UUID

data class ScenarioImportIssue(val index: Int?, val code: String, val message: String)
data class ScenarioImportPreview(
    val valid: Boolean,
    val scenarioIds: List<UUID>,
    val errors: List<ScenarioImportIssue>
)
data class ScenarioImportResult(val imported: Int, val scenarioIds: List<UUID>)

/** Manual, loopback-only demo import until teacher RBAC is available. */
@RestController
@RequestMapping("/api/teacher/scenarios/import")
class ScenarioPackageImport(
    private val mapper: ObjectMapper,
    private val catalog: ClassifierCatalog,
    private val classifier: ClassifierService,
    private val scenarios: ScenarioRepository,
    @Value("\${core.scenario-import.enabled:false}") private val enabled: Boolean,
    @Value("\${core.auth.enabled:false}") private val authEnabled: Boolean
) {
    private val schema by lazy {
        val node = mapper.readTree(catalog.contractsDir().resolve("scenario.schema.json").toFile())
        JsonSchemaFactory.getInstance(SpecVersion.VersionFlag.V202012).getSchema(node)
    }

    @PostMapping("/validate")
    fun validate(@RequestBody body: JsonNode, request: HttpServletRequest): ScenarioImportPreview {
        requireLocalImport(request)
        return inspect(body).first
    }

    @PostMapping
    @ResponseStatus(HttpStatus.CREATED)
    @Transactional
    @Synchronized
    fun import(@RequestBody body: JsonNode, request: HttpServletRequest): ScenarioImportResult {
        requireLocalImport(request)
        val (preview, parsed) = inspect(body)
        if (!preview.valid) {
            val message = preview.errors.take(3).joinToString("; ") { "${it.code}: ${it.message}" }
            if (preview.errors.any { it.code == "DUPLICATE_ID" }) throw IllegalStateException(message)
            throw IllegalArgumentException(message)
        }
        try {
            scenarios.insertAllNew(parsed)
        } catch (_: DuplicateKeyException) {
            throw IllegalStateException("Сценарий с таким id уже существует")
        }
        return ScenarioImportResult(parsed.size, parsed.map { it.id })
    }

    private fun requireLocalImport(request: HttpServletRequest) {
        if (authEnabled || !enabled || request.remoteAddr !in setOf("127.0.0.1", "::1", "0:0:0:0:0:0:0:1")) {
            throw org.springframework.web.server.ResponseStatusException(HttpStatus.FORBIDDEN, "Импорт доступен только локально при явном включении")
        }
    }

    private fun inspect(body: JsonNode): Pair<ScenarioImportPreview, List<Scenario>> {
        val items = body.get("scenarios")
        if (!body.isObject || body.size() != 1 || items == null || !items.isArray || items.size() !in 1..25 ||
            mapper.writeValueAsBytes(body).size > 2_000_000) {
            return ScenarioImportPreview(false, emptyList(), listOf(
                ScenarioImportIssue(null, "PACKAGE_FORMAT", "Нужен объект scenarios с 1–25 элементами размером до 2 МБ")
            )) to emptyList()
        }
        val errors = mutableListOf<ScenarioImportIssue>()
        val parsed = mutableListOf<Scenario>()
        items.forEachIndexed { index, item ->
            schema.validate(item).forEach { violation ->
                errors += ScenarioImportIssue(index, "SCHEMA", violation.message)
            }
            if (errors.any { it.index == index }) return@forEachIndexed
            val scenario = try {
                mapper.treeToValue(item, Scenario::class.java)
            } catch (exception: Exception) {
                errors += ScenarioImportIssue(index, "MODEL", exception.cause?.message ?: exception.message ?: "Невозможно прочитать сценарий")
                return@forEachIndexed
            }
            val truth = scenario.groundTruth
            if (truth.classifierVersion != catalog.classifierVersion) {
                errors += ScenarioImportIssue(index, "CATALOG_VERSION", "Ожидается версия ${catalog.classifierVersion}")
                return@forEachIndexed
            }
            val calculated = try {
                classifier.calculate(truth.expectedInput)
            } catch (exception: IllegalArgumentException) {
                errors += ScenarioImportIssue(index, "INPUT", exception.message ?: "Некорректные признаки или ответы")
                return@forEachIndexed
            }
            if (calculated.status != CalculationStatus.RESOLVED || calculated.classifierCode != truth.classifierCode ||
                calculated.incidentType != truth.incidentType || calculated.ekp35IncidentType != truth.ekp35IncidentType ||
                calculated.responseScenarioCode != truth.responseScenarioCode ||
                calculated.responseScenarioStatus != truth.responseScenarioStatus ||
                calculated.mainServices.map { it.id }.toSet() != truth.mainServices.map { it.id }.toSet() ||
                calculated.services.map { it.id }.toSet() != truth.requiredServices.map { it.id }.toSet()) {
                errors += ScenarioImportIssue(index, "CATALOG_MISMATCH", "Эталон или службы не соответствуют расчёту Core")
                return@forEachIndexed
            }
            // Routing reasons and display names also come from the official catalog.
            parsed += scenario.copy(groundTruth = truth.copy(
                mainServices = calculated.mainServices,
                requiredServices = calculated.services
            ))
        }
        val ids = parsed.map { it.id }
        ids.groupingBy { it }.eachCount().filterValues { it > 1 }.keys.forEach { id ->
            errors += ScenarioImportIssue(null, "DUPLICATE_ID", "id $id повторяется в пакете")
        }
        ids.filter { scenarios.findById(it) != null }.distinct().forEach { id ->
            errors += ScenarioImportIssue(null, "DUPLICATE_ID", "id $id уже существует")
        }
        return ScenarioImportPreview(errors.isEmpty(), ids, errors) to parsed
    }
}
