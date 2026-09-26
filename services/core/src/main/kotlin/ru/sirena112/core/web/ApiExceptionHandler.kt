package ru.sirena112.core.web

import org.springframework.http.HttpStatus
import org.springframework.http.ResponseEntity
import org.springframework.http.converter.HttpMessageNotReadableException
import org.springframework.web.bind.annotation.ExceptionHandler
import org.springframework.web.bind.annotation.RestControllerAdvice
import org.springframework.web.context.request.ServletWebRequest
import org.springframework.web.servlet.NoHandlerFoundException
import org.springframework.web.server.ResponseStatusException
import ru.sirena112.core.domain.InvalidSessionTransitionException
import ru.sirena112.core.integration.UpstreamConflictException
import ru.sirena112.core.integration.UpstreamProtocolException
import ru.sirena112.core.integration.UpstreamUnavailableException
import java.time.Instant
import java.util.NoSuchElementException

@RestControllerAdvice
class ApiExceptionHandler {

    @ExceptionHandler(ResponseStatusException::class)
    fun handleResponseStatus(exception: ResponseStatusException, request: ServletWebRequest): ResponseEntity<ApiError> =
        response(exception.status, "ACCESS_DENIED", exception.reason ?: "Доступ запрещён", request)

    @ExceptionHandler(UpstreamUnavailableException::class)
    fun handleUpstreamUnavailable(exception: UpstreamUnavailableException, request: ServletWebRequest): ResponseEntity<ApiError> =
        response(HttpStatus.SERVICE_UNAVAILABLE, "UPSTREAM_UNAVAILABLE", exception.message ?: "Внешний сервис недоступен", request)

    @ExceptionHandler(UpstreamConflictException::class)
    fun handleUpstreamConflict(exception: UpstreamConflictException, request: ServletWebRequest): ResponseEntity<ApiError> =
        response(HttpStatus.CONFLICT, "UPSTREAM_CONFLICT", exception.message ?: "Конфликт звонка", request)

    @ExceptionHandler(UpstreamProtocolException::class)
    fun handleUpstreamProtocol(exception: UpstreamProtocolException, request: ServletWebRequest): ResponseEntity<ApiError> =
        response(HttpStatus.BAD_GATEWAY, "UPSTREAM_PROTOCOL_ERROR", exception.message ?: "Некорректный ответ внешнего сервиса", request)

    @ExceptionHandler(HttpMessageNotReadableException::class)
    fun handleUnreadable(
        exception: HttpMessageNotReadableException,
        request: ServletWebRequest
    ): ResponseEntity<ApiError> = response(
        status = HttpStatus.BAD_REQUEST,
        code = "BAD_REQUEST",
        message = "Некорректное тело запроса: ${exception.mostSpecificCause.message ?: "не удалось разобрать JSON"}",
        request = request
    )

    @ExceptionHandler(IllegalArgumentException::class)
    fun handleBadRequest(
        exception: IllegalArgumentException,
        request: ServletWebRequest
    ): ResponseEntity<ApiError> = response(
        status = HttpStatus.BAD_REQUEST,
        code = "BAD_REQUEST",
        message = exception.message ?: "Некорректный запрос",
        request = request
    )

    @ExceptionHandler(InvalidSessionTransitionException::class)
    fun handleInvalidTransition(
        exception: InvalidSessionTransitionException,
        request: ServletWebRequest
    ): ResponseEntity<ApiError> = response(
        status = HttpStatus.CONFLICT,
        code = "SESSION_INVALID_TRANSITION",
        message = exception.message ?: "Недопустимый переход учебной сессии",
        request = request
    )

    @ExceptionHandler(NoSuchElementException::class)
    fun handleNotFound(
        exception: NoSuchElementException,
        request: ServletWebRequest
    ): ResponseEntity<ApiError> = response(
        status = HttpStatus.NOT_FOUND,
        code = "NOT_FOUND",
        message = exception.message ?: "Ресурс не найден",
        request = request
    )

    @ExceptionHandler(IllegalStateException::class)
    fun handleConflict(
        exception: IllegalStateException,
        request: ServletWebRequest
    ): ResponseEntity<ApiError> = response(
        status = HttpStatus.CONFLICT,
        code = "INVALID_STATE",
        message = exception.message ?: "Операция недоступна в текущем состоянии",
        request = request
    )

    @ExceptionHandler(NoHandlerFoundException::class)
    fun handleNotFound(
        exception: NoHandlerFoundException,
        request: ServletWebRequest
    ): ResponseEntity<ApiError> = response(
        status = HttpStatus.NOT_FOUND,
        code = "NOT_FOUND",
        message = "Ресурс не найден",
        request = request
    )

    @ExceptionHandler(Exception::class)
    fun handleUnexpected(
        exception: Exception,
        request: ServletWebRequest
    ): ResponseEntity<ApiError> = response(
        status = HttpStatus.INTERNAL_SERVER_ERROR,
        code = "INTERNAL_ERROR",
        message = "Внутренняя ошибка сервиса",
        request = request
    )

    private fun response(
        status: HttpStatus,
        code: String,
        message: String,
        request: ServletWebRequest
    ): ResponseEntity<ApiError> {
        val requestId = request.request.getAttribute("requestId")?.toString()
            ?: request.request.getHeader("X-Request-ID")

        return ResponseEntity.status(status).body(
            ApiError(
                timestamp = Instant.now().toString(),
                status = status.value(),
                code = code,
                message = message,
                path = request.request.requestURI,
                requestId = requestId
            )
        )
    }
}

data class ApiError(
    val timestamp: String,
    val status: Int,
    val code: String,
    val message: String,
    val path: String,
    val requestId: String?
)
