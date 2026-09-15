import org.gradle.api.initialization.resolve.RepositoriesMode

pluginManagement {
    repositories {
        gradlePluginPortal()
        // Some networks reject Gradle HEAD requests to repo.maven.apache.org.
        maven { url = uri("https://repo1.maven.org/maven2") }
        mavenCentral()
    }
}

dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        // Canonical Maven Central endpoint with better compatibility for such networks.
        maven { url = uri("https://repo1.maven.org/maven2") }
        mavenCentral()
    }
}

rootProject.name = "sirena-core"
