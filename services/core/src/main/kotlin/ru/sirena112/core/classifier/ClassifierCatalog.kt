package ru.sirena112.core.classifier

import com.fasterxml.jackson.databind.ObjectMapper
import java.nio.file.Files
import java.nio.file.Path
import java.nio.file.Paths

/**
 * Загруженный нормализованный каталог из задачи #32 c индексами для выбора
 * признаков и вычисления маршрутизации. Каталог один на версию классификатора;
 * обновление версии - повторный импорт и новый файл каталога.
 */
class ClassifierCatalog(private val file: CatalogFile, val location: Path) {

    val classifierVersion: String = file.classifierVersion

    val servicesById: Map<String, CatalogService> = file.services.associateBy { it.id }

    val signsById: Map<String, CatalogSign> = file.signs.associateBy { it.id }

    /** Дети признака по parentId: допустимые следующие уровни иерархии. */
    val signsByParent: Map<String?, List<CatalogSign>> =
        file.signs.groupBy { it.parentId }

    val questionsById: Map<String, CatalogQuestion> = file.questions.associateBy { it.id }

    val columnsByLetter: Map<String, CatalogColumn> =
        file.columns.associateBy { it.sourceColumn }

    val recordsByCode: Map<String, CatalogRecord> =
        file.records.associateBy { it.classifierCode }

    private val recordsByTriple: Map<Triple<String?, String?, String?>, List<CatalogRecord>> =
        file.records.groupBy { Triple(it.signIds.getOrNull(0), it.signIds.getOrNull(1), it.signIds.getOrNull(2)) }

    private val recordsByLevel1: Map<String, List<CatalogRecord>> =
        file.records.filter { !it.signIds[0].isNullOrEmpty() }.groupBy { it.signIds[0]!! }

    private val recordsByLevel2: Map<Pair<String, String>, List<CatalogRecord>> =
        file.records.filter { !it.signIds[0].isNullOrEmpty() && !it.signIds[1].isNullOrEmpty() }
            .groupBy { Pair(it.signIds[0]!!, it.signIds[1]!!) }

    fun serviceRef(id: String): ServiceRef? = servicesById[id]?.let { ServiceRef(it.id, it.displayName) }

    /** Точное совпадение полного пути признаков (недостающие уровни дополняются null). */
    fun recordsForTriple(l1: String?, l2: String?, l3: String?): List<CatalogRecord> =
        recordsByTriple[Triple(l1, l2, l3)] ?: emptyList()

    /** Существуют ли записи, продолжающие выбранный префикс пути на следующий уровень. */
    fun recordsContinuingPrefix(l1: String?, l2: String?): List<CatalogRecord> = when {
        l1 == null -> emptyList()
        l2 == null -> recordsByLevel1[l1] ?: emptyList()
        else -> recordsByLevel2[l1 to l2] ?: emptyList()
    }

    /** Уровень 1 всегда доступен целиком; последующие уровни зависят от родителя. */
    fun topLevelSigns(): List<CatalogSign> = signsByParent[null].orEmpty().sortedBy { it.label }

    fun childrenOf(signId: String): List<CatalogSign> =
        signsByParent[signId].orEmpty().sortedBy { it.label }

    fun recordQuestionDefinitions(record: CatalogRecord): List<CatalogQuestion> =
        record.questionIds.mapNotNull { questionsById[it] }.filter { it.inputType == "SINGLE_SELECT" }

    /** Каталог репозитория с контрактами: используется и для примеров сценариев. */
    fun contractsDir(): Path {
        val dir = location.parent?.parent
        require(dir != null && Files.isDirectory(dir)) { "Каталог contracts не найден рядом с ${location.fileName}" }
        return dir
    }

    companion object {
        const val CATALOG_FILE_NAME = "classifier-v046-11.json"

        /**
         * Каталог - общий артефакт репозитория, а не ресурс сервиса. Путь задаётся
         * конфигурацией; по умолчанию ищется contracts/catalog от текущего каталога
         * вверх, чтобы сервис можно было запускать и из services/core, и из корня.
         */
        fun load(configuredPath: String?, objectMapper: ObjectMapper): ClassifierCatalog {
            val path = resolveLocation(configuredPath)
            val file = objectMapper.readValue(path.toFile(), CatalogFile::class.java)
            require(file.schemaVersion == "1.0.0") {
                "Не поддерживаемая версия схемы каталога: ${file.schemaVersion}"
            }
            return ClassifierCatalog(file, path)
        }

        private fun resolveLocation(configuredPath: String?): Path {
            if (!configuredPath.isNullOrBlank()) {
                val p = Paths.get(configuredPath)
                require(Files.isRegularFile(p)) { "Файл классификатора не найден: $configuredPath" }
                return p
            }
            var dir: Path? = Paths.get("").toAbsolutePath()
            repeat(8) {
                val current = dir ?: return@repeat
                val candidate = current.resolve("contracts/catalog/$CATALOG_FILE_NAME")
                if (Files.isRegularFile(candidate)) return candidate
                dir = current.parent
            }
            throw IllegalArgumentException(
                "Файл классификатора $CATALOG_FILE_NAME не найден; укажите core.classifier-catalog-path"
            )
        }
    }
}
