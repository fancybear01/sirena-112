package ru.sirena112.core.web

import org.springframework.http.HttpStatus
import org.springframework.http.ResponseEntity
import org.springframework.web.bind.annotation.ExceptionHandler
import org.springframework.web.bind.annotation.RestControllerAdvice
import org.springframework.web.context.request.ServletWebRequest
import org.springframework.web.servlet.NoHandlerFoundException
import java.time.Instant

@RestControllerAdvice
class ApiExceptionHandler {

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
