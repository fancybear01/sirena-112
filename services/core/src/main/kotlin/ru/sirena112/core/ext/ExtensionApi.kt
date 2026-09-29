package ru.sirena112.core.ext

import org.springframework.beans.factory.annotation.Value
import org.springframework.context.annotation.Bean
import org.springframework.context.annotation.Configuration
import org.springframework.core.annotation.Order
import org.springframework.http.HttpStatus
import org.springframework.security.config.annotation.web.builders.HttpSecurity
import org.springframework.security.config.http.SessionCreationPolicy
import org.springframework.security.web.SecurityFilterChain
import org.springframework.security.web.authentication.UsernamePasswordAuthenticationFilter
import org.springframework.web.bind.annotation.GetMapping
import org.springframework.web.bind.annotation.PathVariable
import org.springframework.web.bind.annotation.RequestMapping
import org.springframework.web.bind.annotation.RequestParam
import org.springframework.web.bind.annotation.RestController
import org.springframework.web.filter.OncePerRequestFilter
import org.springframework.web.server.ResponseStatusException
import ru.sirena112.core.card.SessionReportRepository
import ru.sirena112.core.domain.ScenarioRepository
import ru.sirena112.core.domain.SessionEventRepository
import ru.sirena112.core.domain.TrainingSessionRepository
import java.nio.charset.StandardCharsets
import java.security.MessageDigest
import java.util.UUID
import javax.servlet.FilterChain
import javax.servlet.http.HttpServletRequest
import javax.servlet.http.HttpServletResponse

/**
 * Версионированный API только для чтения, для локальных расширений. Задача #97.
 *
 * Зачем отдельная поверхность, а не существующие /api/teacher и /api/student.
 * Те предназначены человеку в браузере: держат сессию, проверяют CSRF и роль
 * пользователя. Расширение - это программа, у неё нет пользователя и сессии.
 * Смешивать их в одном пространстве значит либо ослабить правила для людей,
 * либо навязать программе непригодный способ входа.
 *
 * Правила поверхности:
 *
 * - **только чтение.** Менять бизнес-данные расширение не может: для этого
 *   есть команды Core, которые проверяют переходы состояний и права. Иначе
 *   расширение обошло бы правила, ради которых Core существует.
 * - **свой сервисный токен.** CORE_EXT_SERVICE_TOKEN, не тот же, что у Media:
 *   отзыв доступа расширению не должен ломать телефонию.
 * - **версия в пути.** /api/ext/v1: несовместимое изменение появится как v2,
 *   а v1 продолжит работать, пока её не объявят устаревшей.
 * - **личных данных не отдаём.** Ни имён, ни логинов, ни карточек, ни
 *   транскриптов. Расширению нужны факты об обучении, а не о людях.
 * - **постраничная выдача обязательна.** Без предела ответа одно обращение
 *   к тысяче занятий уложило бы Core.
 */
const val EXT_API_VERSION = "v1"

/** Сколько записей отдаём за один раз, если размер не задан. */
const val EXT_DEFAULT_PAGE_SIZE = 50

/** Жёсткий предел: защита от запроса «отдай всё» одним обращением. */
const val EXT_MAX_PAGE_SIZE = 200

data class ExtPage<T>(
    val items: List<T>,
    val page: Int,
    val size: Int,
    val total: Int,
    val requestId: String?
)

data class ExtMeta(
    val apiVersion: String,
    val readOnly: Boolean,
    val classifierVersion: String?,
    val maxPageSize: Int,
    val limitations: List<String>,
    val requestId: String?
)

/** Сценарий без эталонного ввода: расширению не нужен ответ на задание. */
data class ExtScenario(
    val id: UUID,
    val version: Int,
    val title: String,
    val category: String,
    val difficulty: String,
    val classifierVersion: String,
    val classifierCode: String,
    val incidentType: String
)

/**
 * Занятие без карточки, без имён и без идентификатора обучающегося.
 * Группа отдаётся: по ней расширение строит сводки, и она не указывает
 * на человека.
 */
data class ExtSession(
    val id: UUID,
    val scenarioId: UUID,
    val mode: String,
    val state: String,
    val groupId: UUID?,
    val createdAt: String,
    val startedAt: String?,
    val endedAt: String?
)

/** Результат занятия: баллы и критерии, без текста карточки. */
data class ExtResult(
    val sessionId: UUID,
    val classifierVersion: String?,
    val totalScore: Double,
    val maxScore: Double,
    val passed: Boolean,
    val criteria: List<ExtCriterion>,
    val requestId: String?
)

data class ExtCriterion(val code: String, val passed: Boolean, val points: Double, val maxPoints: Double)

/** Событие занятия без полезной нагрузки: она может содержать транскрипт. */
data class ExtEvent(
    val eventId: UUID,
    val sessionId: UUID,
    val type: String,
    val source: String,
    val occurredAt: String
)

@RestController
@RequestMapping("/api/ext/$EXT_API_VERSION")
class ExtensionApiController(
    private val scenarios: ScenarioRepository,
    private val sessions: TrainingSessionRepository,
    private val reports: SessionReportRepository,
    private val events: SessionEventRepository
) {
    @GetMapping("/meta")
    fun meta(request: HttpServletRequest): ExtMeta = ExtMeta(
        apiVersion = EXT_API_VERSION,
        readOnly = true,
        classifierVersion = scenarios.findAll().firstOrNull()?.groundTruth?.classifierVersion,
        maxPageSize = EXT_MAX_PAGE_SIZE,
        limitations = listOf(
            "Только чтение: изменение данных доступно лишь через команды Core.",
            "Персональные данные не отдаются: ни имён, ни логинов, ни карточек, ни транскриптов.",
            "Выдача постраничная, размер страницы не больше $EXT_MAX_PAGE_SIZE.",
            "Прямой доступ к PostgreSQL расширению не нужен и не предусмотрен."
        ),
        requestId = requestId(request)
    )

    @GetMapping("/scenarios")
    fun scenarios(
        @RequestParam(defaultValue = "0") page: Int,
        @RequestParam(defaultValue = "$EXT_DEFAULT_PAGE_SIZE") size: Int,
        request: HttpServletRequest
    ): ExtPage<ExtScenario> {
        val all = scenarios.findAll().map {
            ExtScenario(it.id, it.version, it.title, it.category.name, it.difficulty.name,
                it.groundTruth.classifierVersion, it.groundTruth.classifierCode,
                it.groundTruth.incidentType)
        }
        return paged(all, page, size, request)
    }

    @GetMapping("/sessions")
    fun sessions(
        @RequestParam(defaultValue = "0") page: Int,
        @RequestParam(defaultValue = "$EXT_DEFAULT_PAGE_SIZE") size: Int,
        @RequestParam(required = false) state: String?,
        request: HttpServletRequest
    ): ExtPage<ExtSession> {
        val wanted = state?.trim()?.uppercase()?.takeIf { it.isNotEmpty() }
        val all = sessions.findAll()
            .filter { wanted == null || it.state.name == wanted }
            .map {
                ExtSession(it.id, it.scenario.id, it.mode.name, it.state.name, it.groupId,
                    it.createdAt.toString(), it.startedAt?.toString(), it.endedAt?.toString())
            }
        return paged(all, page, size, request)
    }

    @GetMapping("/sessions/{sessionId}/result")
    fun result(@PathVariable sessionId: UUID, request: HttpServletRequest): ExtResult {
        val report = reports.findBySessionIdOrNull(sessionId)
            ?: throw ResponseStatusException(HttpStatus.NOT_FOUND, "Отчёт для занятия не найден")
        return ExtResult(
            sessionId = report.sessionId,
            classifierVersion = report.classifierVersion,
            totalScore = report.score,
            maxScore = report.maxScore,
            passed = report.passed,
            // message критерия не отдаём: это текст для человека, а не факт
            // для программы, и он может меняться без смены версии API.
            criteria = report.criteria.map {
                ExtCriterion(it.code, it.passed, it.points, it.maxPoints)
            },
            requestId = requestId(request)
        )
    }

    @GetMapping("/sessions/{sessionId}/events")
    fun events(
        @PathVariable sessionId: UUID,
        @RequestParam(defaultValue = "0") page: Int,
        @RequestParam(defaultValue = "$EXT_DEFAULT_PAGE_SIZE") size: Int,
        request: HttpServletRequest
    ): ExtPage<ExtEvent> {
        if (sessions.findById(sessionId) == null) {
            throw ResponseStatusException(HttpStatus.NOT_FOUND, "Занятие не найдено")
        }
        val all = events.findBySessionId(sessionId).map {
            ExtEvent(it.eventId, it.sessionId, it.type, it.source, it.timestamp.toString())
        }
        return paged(all, page, size, request)
    }

    private fun <T> paged(all: List<T>, page: Int, size: Int, request: HttpServletRequest): ExtPage<T> {
        if (page < 0) throw ResponseStatusException(HttpStatus.BAD_REQUEST, "page не может быть отрицательным")
        if (size < 1) throw ResponseStatusException(HttpStatus.BAD_REQUEST, "size должен быть не меньше 1")
        // Слишком большой size не отклоняем, а урезаем: расширение получит
        // данные и увидит фактический размер страницы в ответе. Отказ здесь
        // ломал бы чужой код там, где достаточно ограничить.
        val effective = minOf(size, EXT_MAX_PAGE_SIZE)
        val from = minOf(page * effective, all.size)
        val to = minOf(from + effective, all.size)
        return ExtPage(all.subList(from, to), page, effective, all.size, requestId(request))
    }

    private fun requestId(request: HttpServletRequest): String? =
        request.getAttribute("requestId")?.toString()
}

/**
 * Отдельная цепочка безопасности для расширений.
 *
 * Сделана дополнительным бином, а существующие цепочки не меняются: правка
 * конфигурации входа людей - самое опасное место в сервисе, и трогать её
 * ради новой поверхности незачем.
 *
 * Порядок 0 означает, что эта цепочка отвечает за путь api/ext раньше
 * остальных. Косая черта со звёздочками здесь не пишется намеренно:
 * в Kotlin блочные комментарии вкладываются, и такая пара открыла бы
 * вложенный комментарий, оставив внешний незакрытым. Токен требуется всегда, в том числе в демонстрационном режиме
 * без авторизации: расширение - это программа, и открывать ей данные просто
 * потому, что демонстрация запущена без входа, неправильно.
 */
@Configuration
class ExtensionApiSecurityConfiguration {
    @Bean
    @Order(0)
    fun extensionApiSecurity(
        http: HttpSecurity,
        @Value("\${core.ext.service-token:}") token: String
    ): SecurityFilterChain {
        http.antMatcher("/api/ext/**")
            .csrf().disable()
            .sessionManagement().sessionCreationPolicy(SessionCreationPolicy.STATELESS).and()
            .authorizeRequests().anyRequest().permitAll().and()
            .addFilterBefore(ExtensionTokenFilter(token), UsernamePasswordAuthenticationFilter::class.java)
        return http.build()
    }
}

/**
 * Проверка сервисного токена расширения.
 *
 * Пустой токен означает, что поверхность выключена: отвечаем 503, а не
 * открываем доступ. Молчаливое «токен не настроен, значит пускаем» - тот
 * самый случай, когда защита выглядит работающей и не работает.
 *
 * Сравнение по байтам через MessageDigest.isEqual: постоянное время и нет
 * зависимости от кодировки.
 */
// internal, а не private: поведение при пустом и неверном токене
// проверяется тестом напрямую, без поднятия контекста Spring.
internal const val BEARER = "Bearer "

internal class ExtensionTokenFilter(internal val token: String) : OncePerRequestFilter() {
    override fun doFilterInternal(
        request: HttpServletRequest,
        response: HttpServletResponse,
        chain: FilterChain
    ) {
        if (token.isBlank()) {
            response.sendError(HttpStatus.SERVICE_UNAVAILABLE.value(),
                "API расширений выключен: задайте CORE_EXT_SERVICE_TOKEN")
            return
        }
        // Приставка обязательна. removePrefix оставляет строку как есть,
        // если приставки нет, и тогда принимался бы ещё и голый токен -
        // второй формат, которого нет в описании API. Тест это поймал.
        val header = request.getHeader("Authorization") ?: ""
        val candidate = if (header.startsWith(BEARER)) header.removePrefix(BEARER) else ""
        val expected = token.toByteArray(StandardCharsets.UTF_8)
        if (!MessageDigest.isEqual(candidate.toByteArray(StandardCharsets.UTF_8), expected)) {
            response.sendError(HttpStatus.UNAUTHORIZED.value())
            return
        }
        chain.doFilter(request, response)
    }
}
