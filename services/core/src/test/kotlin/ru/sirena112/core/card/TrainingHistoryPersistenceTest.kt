package ru.sirena112.core.card

import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Test
import org.springframework.beans.factory.annotation.Autowired
import org.springframework.boot.test.context.SpringBootTest
import org.springframework.jdbc.core.JdbcTemplate
import java.time.Instant
import java.util.UUID

/** A new repository instance sees feedback written before a simulated Core restart. */
@SpringBootTest(properties = ["spring.datasource.url=jdbc:h2:mem:history-persistence;DB_CLOSE_DELAY=-1;MODE=PostgreSQL"])
class TrainingHistoryPersistenceTest {
    @Autowired lateinit var jdbc: JdbcTemplate

    @Test fun `feedback survives repository recreation`() {
        val authorId = UUID.randomUUID()
        val sessionId = UUID.randomUUID()
        jdbc.execute("""CREATE TABLE IF NOT EXISTS training_feedback (
            id UUID PRIMARY KEY, session_id UUID NOT NULL, author_id UUID NOT NULL,
            kind VARCHAR(16) NOT NULL, text VARCHAR(2000) NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL, old_score DOUBLE PRECISION, new_score DOUBLE PRECISION)""")
        val first = PostgresTrainingFeedbackRepository(jdbc)
        val feedback = TrainingFeedback(UUID.randomUUID(), sessionId, authorId, FeedbackKind.CORRECTION,
            "Проверено по эталону", Instant.now(), 60.0, 75.0)
        first.append(feedback)
        val afterRestart = PostgresTrainingFeedbackRepository(jdbc).findBySessionId(sessionId)
        assertEquals(1, afterRestart.size)
        assertEquals(feedback.id, afterRestart.single().id)
        assertEquals(60.0, afterRestart.single().oldScore)
        assertEquals(75.0, afterRestart.single().newScore)
    }
}
