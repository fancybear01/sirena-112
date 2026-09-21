package ru.sirena112.core.integration

class UpstreamUnavailableException(message: String, cause: Throwable? = null) : RuntimeException(message, cause)

class UpstreamConflictException(message: String, cause: Throwable? = null) : RuntimeException(message, cause)

class UpstreamProtocolException(message: String, cause: Throwable? = null) : RuntimeException(message, cause)
