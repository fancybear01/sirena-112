package ru.sirena112.core.web

import org.slf4j.MDC
import org.springframework.stereotype.Component
import org.springframework.web.filter.OncePerRequestFilter
import java.util.UUID
import javax.servlet.FilterChain
import javax.servlet.http.HttpServletRequest
import javax.servlet.http.HttpServletResponse

@Component
class RequestIdFilter : OncePerRequestFilter() {
    override fun doFilterInternal(
        request: HttpServletRequest,
        response: HttpServletResponse,
        filterChain: FilterChain
    ) {
        val requestId = request.getHeader(REQUEST_ID_HEADER)?.takeIf { it.isNotBlank() }
            ?: UUID.randomUUID().toString()

        response.setHeader(REQUEST_ID_HEADER, requestId)
        request.setAttribute(MDC_KEY, requestId)
        MDC.put(MDC_KEY, requestId)
        val sessionId = request.getHeader(SESSION_ID_HEADER)?.takeIf { it.isNotBlank() }
        if (sessionId != null) {
            request.setAttribute(SESSION_ID_MDC_KEY, sessionId)
            MDC.put(SESSION_ID_MDC_KEY, sessionId)
        }
        try {
            filterChain.doFilter(request, response)
        } finally {
            MDC.remove(MDC_KEY)
            if (sessionId != null) {
                MDC.remove(SESSION_ID_MDC_KEY)
            }
        }
    }

    private companion object {
        const val REQUEST_ID_HEADER = "X-Request-ID"
        const val SESSION_ID_HEADER = "X-Session-ID"
        const val MDC_KEY = "requestId"
        const val SESSION_ID_MDC_KEY = "sessionId"
    }
}
