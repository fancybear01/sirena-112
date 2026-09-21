package ru.sirena112.core.classifier

import com.fasterxml.jackson.databind.JsonNode
import com.fasterxml.jackson.databind.ObjectMapper
import java.nio.file.Files
import java.nio.file.Path
import java.nio.file.Paths

/** Доступ к общим артефактам contracts/ из тестов: каталог и фикстуры сценариев. */
object ContractTestSupport {

    val objectMapper: ObjectMapper = ObjectMapper().findAndRegisterModules()

    fun repoRoot(): Path {
        var dir: Path? = Paths.get("").toAbsolutePath()
        repeat(8) {
            val current = dir ?: return@repeat
            if (Files.isRegularFile(current.resolve("contracts/catalog/${ClassifierCatalog.CATALOG_FILE_NAME}"))) {
                return current
            }
            dir = current.parent
        }
        throw IllegalStateException("Корень репозитория с contracts/ не найден от ${Paths.get("").toAbsolutePath()}")
    }

    fun catalog(): ClassifierCatalog = ClassifierCatalog.load(null, objectMapper)

    fun fixtureNode(name: String): JsonNode =
        objectMapper.readTree(repoRoot().resolve("contracts/examples/$name").toFile())
}
