package ru.sirena112.core.auth

import org.springframework.beans.factory.annotation.Value
import org.springframework.boot.ApplicationRunner
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty
import org.springframework.context.annotation.Bean
import org.springframework.context.annotation.Configuration
import org.springframework.core.annotation.Order
import org.springframework.http.HttpStatus
import org.springframework.http.MediaType
import org.springframework.security.authentication.ProviderManager
import org.springframework.security.authentication.dao.DaoAuthenticationProvider
import org.springframework.security.config.annotation.web.builders.HttpSecurity
import org.springframework.security.config.http.SessionCreationPolicy
import org.springframework.security.core.userdetails.User
import org.springframework.security.core.userdetails.UserDetailsService
import org.springframework.security.crypto.factory.PasswordEncoderFactories
import org.springframework.security.crypto.password.PasswordEncoder
import org.springframework.security.web.SecurityFilterChain
import org.springframework.security.web.authentication.UsernamePasswordAuthenticationFilter
import org.springframework.security.web.access.intercept.FilterSecurityInterceptor
import org.springframework.security.web.csrf.CookieCsrfTokenRepository
import org.springframework.web.filter.OncePerRequestFilter
import java.nio.charset.StandardCharsets
import java.security.MessageDigest
import java.util.UUID
import javax.servlet.FilterChain
import javax.servlet.http.HttpServletRequest
import javax.servlet.http.HttpServletResponse

@Configuration
class AuthSecurityConfiguration {
    @Bean fun passwordEncoder(): PasswordEncoder = PasswordEncoderFactories.createDelegatingPasswordEncoder()

    @Bean
    @ConditionalOnProperty(name = ["core.auth.enabled"], havingValue = "true")
    fun accountDetails(accounts: AccountRepository): UserDetailsService = UserDetailsService { username ->
        val account = accounts.findByUsername(username)
            ?: throw org.springframework.security.core.userdetails.UsernameNotFoundException("Учётная запись не найдена")
        User.withUsername(account.username).password(account.passwordHash).roles(account.role.name)
            .accountLocked(account.locked).disabled(!account.enabled).build()
    }

    @Bean
    @ConditionalOnProperty(name = ["core.auth.enabled"], havingValue = "true")
    fun authenticationManager(details: UserDetailsService, encoder: PasswordEncoder): ProviderManager =
        ProviderManager(DaoAuthenticationProvider().also {
            it.setUserDetailsService(details)
            it.setPasswordEncoder(encoder)
        })

    @Bean
    @ConditionalOnProperty(name = ["core.auth.enabled"], havingValue = "true")
    fun bootstrapAdmin(accounts: AccountRepository, encoder: PasswordEncoder,
        @Value("\${core.auth.bootstrap-admin-username:}") username: String,
        @Value("\${core.auth.bootstrap-admin-password:}") password: String,
        @Value("\${core.auth.media-token:}") mediaToken: String
    ) = ApplicationRunner {
        require(mediaToken.length >= 32) { "CORE_MEDIA_SERVICE_TOKEN должен содержать не менее 32 символов" }
        if (accounts.findAll().isEmpty()) {
            require(username.matches(Regex("[a-zA-Z0-9_.-]{3,80}"))) { "Задайте CORE_BOOTSTRAP_ADMIN_USERNAME" }
            require(password.length >= 12) { "Задайте CORE_BOOTSTRAP_ADMIN_PASSWORD длиной не менее 12 символов" }
            accounts.insert(AuthAccount(UUID.randomUUID(), username.lowercase(), encoder.encode(password), Role.ADMIN, "Administrator"))
        }
    }

    @Bean
    @Order(1)
    @ConditionalOnProperty(name = ["core.auth.enabled"], havingValue = "true")
    fun internalSecurity(http: HttpSecurity, @Value("\${core.auth.media-token:}") mediaToken: String): SecurityFilterChain {
        http.antMatcher("/internal/**")
            .csrf().disable()
            .sessionManagement().sessionCreationPolicy(SessionCreationPolicy.STATELESS).and()
            .authorizeRequests().anyRequest().permitAll().and()
            .addFilterBefore(MediaServiceTokenFilter(mediaToken), UsernamePasswordAuthenticationFilter::class.java)
        return http.build()
    }

    @Bean
    @Order(2)
    @ConditionalOnProperty(name = ["core.auth.enabled"], havingValue = "true")
    fun userSecurity(http: HttpSecurity, accounts: AccountRepository, audit: AuthAuditRepository): SecurityFilterChain {
        http.csrf().csrfTokenRepository(CookieCsrfTokenRepository.withHttpOnlyFalse()).and()
            .authorizeRequests()
            .antMatchers("/health", "/health/**", "/ready", "/actuator/health/**", "/api/auth/csrf", "/api/auth/login").permitAll()
            .antMatchers("/api/auth/me", "/api/auth/logout").authenticated()
            .antMatchers("/api/admin/**").hasRole("ADMIN")
            .antMatchers("/api/teacher/**").hasAnyRole("ADMIN", "TEACHER")
            .antMatchers("/api/student/**").hasRole("STUDENT")
            .antMatchers("/ws/**").authenticated()
            .anyRequest().denyAll().and()
            .exceptionHandling()
            .authenticationEntryPoint { _, response, _ -> response.sendError(HttpStatus.UNAUTHORIZED.value()) }
            .accessDeniedHandler { request, response, _ ->
                val username = org.springframework.security.core.context.SecurityContextHolder.getContext().authentication?.name
                audit.append(AuthAudit(username?.let { accounts.findByUsername(it)?.id }, "ACCESS_DENIED", null, "DENIED",
                    request.getAttribute("requestId")?.toString()))
                response.sendError(HttpStatus.FORBIDDEN.value())
            }.and()
            .sessionManagement().sessionCreationPolicy(SessionCreationPolicy.IF_REQUIRED).and()
            .formLogin().disable().httpBasic().disable().logout().disable()
        http.addFilterBefore(ActiveAccountFilter(accounts), FilterSecurityInterceptor::class.java)
        return http.build()
    }

    @Bean
    @Order(3)
    @ConditionalOnProperty(name = ["core.auth.enabled"], havingValue = "false", matchIfMissing = true)
    fun demoSecurity(http: HttpSecurity): SecurityFilterChain {
        http.csrf().disable().authorizeRequests().anyRequest().permitAll()
        return http.build()
    }
}

private class ActiveAccountFilter(private val accounts: AccountRepository) : OncePerRequestFilter() {
    override fun doFilterInternal(request: HttpServletRequest, response: HttpServletResponse, chain: FilterChain) {
        val authentication = org.springframework.security.core.context.SecurityContextHolder.getContext().authentication
        if (authentication != null && authentication.isAuthenticated &&
            authentication !is org.springframework.security.authentication.AnonymousAuthenticationToken) {
            val account = accounts.findByUsername(authentication.name)
            if (account == null || account.locked || !account.enabled ||
                authentication.authorities.none { it.authority == "ROLE_${account.role.name}" }) {
                request.getSession(false)?.invalidate()
                org.springframework.security.core.context.SecurityContextHolder.clearContext()
                response.sendError(HttpStatus.UNAUTHORIZED.value())
                return
            }
        }
        chain.doFilter(request, response)
    }
}

private class MediaServiceTokenFilter(private val token: String) : OncePerRequestFilter() {
    override fun doFilterInternal(request: HttpServletRequest, response: HttpServletResponse, chain: FilterChain) {
        val candidate = request.getHeader("Authorization")?.removePrefix("Bearer ") ?: ""
        if (token.isBlank() || !MessageDigest.isEqual(candidate.toByteArray(StandardCharsets.UTF_8),
                token.toByteArray(StandardCharsets.UTF_8))) {
            response.sendError(HttpStatus.UNAUTHORIZED.value())
            return
        }
        chain.doFilter(request, response)
    }
}
