"""
Initialize database with all required tables for Phase 1 testing.
"""
from database import engine
from sqlalchemy import text

# SQLite-compatible schema (converted from db.txt)
SCHEMA = """
-- 1. Users Table
CREATE TABLE IF NOT EXISTS users (
    id VARCHAR PRIMARY KEY,
    email VARCHAR UNIQUE NOT NULL,
    password_hash VARCHAR NOT NULL,
    last_active_language VARCHAR,
    total_exams_taken INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW()
);

-- 2. Student State (The "Live" Mastery Matrix)
CREATE TABLE IF NOT EXISTS student_state (
    user_id VARCHAR REFERENCES users(id) ON DELETE CASCADE,
    mapping_id VARCHAR NOT NULL,
    language_id VARCHAR NOT NULL,
    mastery_score FLOAT DEFAULT 0.0, 
    confidence_score FLOAT DEFAULT 0.0,
    fluency_score FLOAT DEFAULT 0.0,
    last_practiced_at TIMESTAMP DEFAULT NOW(),
    last_updated TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (user_id, mapping_id, language_id)
);

-- 3. Question Bank
CREATE TABLE IF NOT EXISTS question_bank (
    id VARCHAR PRIMARY KEY,
    content_hash VARCHAR UNIQUE NOT NULL,
    mapping_id VARCHAR NOT NULL,
    language_id VARCHAR NOT NULL,
    sub_topic VARCHAR,
    difficulty FLOAT NOT NULL,
    question_data JSONB NOT NULL,
    is_verified BOOLEAN DEFAULT FALSE,
    quality_score FLOAT DEFAULT 0.5,
    times_used INTEGER DEFAULT 0,
    times_correct INTEGER DEFAULT 0,
    calibrated_difficulty FLOAT,
    created_at TIMESTAMP DEFAULT NOW(),
    created_by VARCHAR DEFAULT 'gemini-1.5-pro'
);

-- 4. User Question History (tracks which questions each user has seen)
CREATE TABLE IF NOT EXISTS user_question_history (
    id VARCHAR PRIMARY KEY,
    user_id VARCHAR NOT NULL,
    question_id VARCHAR REFERENCES question_bank(id) ON DELETE CASCADE,
    session_id VARCHAR,
    was_correct BOOLEAN,
    time_spent_seconds FLOAT,
    seen_at TIMESTAMP DEFAULT NOW()
);

-- 5. Exam Sessions (with Phase 2B: Adaptive Difficulty, Phase 2C: Review Type, Phase 3: Session Lifecycle)
CREATE TABLE IF NOT EXISTS exam_sessions (
    id VARCHAR PRIMARY KEY,
    user_id VARCHAR REFERENCES users(id) ON DELETE CASCADE,
    language_id VARCHAR NOT NULL,
    major_topic_id VARCHAR NOT NULL,
    session_type VARCHAR DEFAULT 'practice',  -- 'practice', 'diagnostic', 'review'
    session_status VARCHAR DEFAULT 'started',  -- 'started', 'completed', 'abandoned'
    overall_score FLOAT,
    difficulty_assigned FLOAT,
    time_taken_seconds INTEGER,
    rl_action_taken VARCHAR,
    recommended_next_difficulty FLOAT DEFAULT 0.5,
    started_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW()
);

-- 6. Exam Details (Individual Question Results)
CREATE TABLE IF NOT EXISTS exam_details (
    id SERIAL PRIMARY KEY,
    session_id VARCHAR REFERENCES exam_sessions(id) ON DELETE CASCADE,
    questions_snapshot JSONB NOT NULL,
    recommendations JSONB,
    synergy_applied BOOLEAN DEFAULT FALSE
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_student_state_user ON student_state(user_id);
CREATE INDEX IF NOT EXISTS idx_exam_sessions_user ON exam_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_exam_sessions_status ON exam_sessions(session_status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_question_bank_mapping_lang ON question_bank(mapping_id, language_id);
CREATE INDEX IF NOT EXISTS idx_question_bank_difficulty ON question_bank(difficulty);

-- Phase 2B: Adaptive difficulty optimization (10-session window queries)
CREATE INDEX IF NOT EXISTS idx_adaptive_difficulty_window ON exam_sessions(user_id, language_id, major_topic_id, created_at DESC);

-- 7. Phase 2C: Review Schedule (Spaced Repetition)
CREATE TABLE IF NOT EXISTS review_schedule (
    id VARCHAR PRIMARY KEY,
    user_id VARCHAR REFERENCES users(id) ON DELETE CASCADE,
    language_id VARCHAR NOT NULL,
    mapping_id VARCHAR NOT NULL,
    
    -- Review metadata
    current_mastery FLOAT NOT NULL,
    mastery_at_last_review FLOAT,
    days_since_last_review INTEGER DEFAULT 0,
    
    -- Scheduling
    next_review_date TIMESTAMP NOT NULL,
    review_interval_days INTEGER NOT NULL,
    review_priority INTEGER DEFAULT 0,
    
    -- Performance tracking
    successful_reviews INTEGER DEFAULT 0,
    failed_reviews INTEGER DEFAULT 0,
    personal_decay_rate FLOAT DEFAULT 0.02,
    
    -- Timestamps
    last_reviewed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    
    UNIQUE(user_id, language_id, mapping_id)
);

-- Phase 2C: Indexes for review queries
CREATE INDEX IF NOT EXISTS idx_review_schedule_lookup ON review_schedule(user_id, language_id, next_review_date);
CREATE INDEX IF NOT EXISTS idx_review_schedule_due ON review_schedule(next_review_date);

-- 8. Phase 2D: Error History (Advanced Error Pattern Analysis)
CREATE TABLE IF NOT EXISTS error_history (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR REFERENCES users(id) ON DELETE CASCADE,
    language_id VARCHAR NOT NULL,
    mapping_id VARCHAR NOT NULL,
    session_id VARCHAR REFERENCES exam_sessions(id) ON DELETE CASCADE,
    question_id VARCHAR NOT NULL,
    
    -- Error details
    error_type VARCHAR NOT NULL,
    error_category VARCHAR NOT NULL,
    severity FLOAT NOT NULL,
    
    -- Context
    difficulty_tier INTEGER DEFAULT 1,
    is_corrected BOOLEAN DEFAULT FALSE,
    
    -- Timestamps
    occurred_at TIMESTAMP DEFAULT NOW(),
    corrected_at TIMESTAMP
);

-- Phase 2D: Indexes for pattern analysis queries
CREATE INDEX IF NOT EXISTS idx_error_history_user ON error_history(user_id, language_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_error_history_pattern ON error_history(user_id, error_type, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_error_history_session ON error_history(session_id);

-- 9. User State Vectors (for analytics service - stores session snapshots)
CREATE TABLE IF NOT EXISTS user_state_vectors (
    id VARCHAR PRIMARY KEY,
    user_id VARCHAR REFERENCES users(id) ON DELETE CASCADE,
    language_id VARCHAR NOT NULL,
    session_snapshot JSONB NOT NULL,
    last_updated TIMESTAMP DEFAULT NOW(),
    created_at TIMESTAMP DEFAULT NOW()
);

-- 10. Learning Paths (frontend feature)
CREATE TABLE IF NOT EXISTS learning_paths (
    id VARCHAR PRIMARY KEY,
    user_id VARCHAR REFERENCES users(id) ON DELETE CASCADE,
    language_id VARCHAR NOT NULL,
    path_name VARCHAR NOT NULL,
    description TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    progress_percentage FLOAT DEFAULT 0.0,
    topics_completed INTEGER DEFAULT 0,
    total_topics INTEGER NOT NULL,
    current_topic VARCHAR,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP
);

-- 11. Question Reports (admin feature)
CREATE TABLE IF NOT EXISTS question_reports (
    id VARCHAR PRIMARY KEY,
    question_id VARCHAR REFERENCES question_bank(id) ON DELETE CASCADE,
    reported_by VARCHAR REFERENCES users(id) ON DELETE SET NULL,
    report_reason VARCHAR NOT NULL,
    description TEXT,
    status VARCHAR DEFAULT 'pending',
    resolved_by VARCHAR REFERENCES users(id) ON DELETE SET NULL,
    resolution_notes TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    resolved_at TIMESTAMP
);

-- 12. User Queries (support ticket system)
CREATE TABLE IF NOT EXISTS user_queries (
    id VARCHAR PRIMARY KEY,
    user_id VARCHAR REFERENCES users(id) ON DELETE CASCADE,
    category VARCHAR NOT NULL,
    priority VARCHAR DEFAULT 'medium',
    subject VARCHAR NOT NULL,
    message TEXT NOT NULL,
    status VARCHAR DEFAULT 'open',
    assigned_to VARCHAR REFERENCES users(id) ON DELETE SET NULL,
    replies JSONB,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    resolved_at TIMESTAMP
);

-- 13. Admin Logs (audit trail)
CREATE TABLE IF NOT EXISTS admin_logs (
    id SERIAL PRIMARY KEY,
    admin_id VARCHAR REFERENCES users(id) ON DELETE SET NULL,
    action_type VARCHAR NOT NULL,
    target_type VARCHAR,
    target_id VARCHAR,
    details JSONB,
    ip_address VARCHAR,
    created_at TIMESTAMP DEFAULT NOW()
);

-- 14. Notification Preferences
CREATE TABLE IF NOT EXISTS notification_preferences (
    user_id VARCHAR PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    email_notifications BOOLEAN DEFAULT TRUE,
    test_reminders BOOLEAN DEFAULT TRUE,
    weekly_progress BOOLEAN DEFAULT TRUE,
    achievement_alerts BOOLEAN DEFAULT TRUE,
    updated_at TIMESTAMP DEFAULT NOW()
);

-- 15. RL Recommendation History (Phase 2: Track RL decisions)
CREATE TABLE IF NOT EXISTS rl_recommendation_history (
    id VARCHAR PRIMARY KEY,
    user_id VARCHAR REFERENCES users(id) ON DELETE CASCADE,
    language_id VARCHAR NOT NULL,
    strategy VARCHAR NOT NULL,
    mapping_id VARCHAR NOT NULL,
    major_topic_id VARCHAR NOT NULL,
    difficulty FLOAT NOT NULL,
    action_id INTEGER NOT NULL,
    confidence FLOAT,
    prerequisite_check_passed BOOLEAN NOT NULL,
    metadata JSONB,
    created_at TIMESTAMP DEFAULT NOW(),
    followed_up BOOLEAN DEFAULT FALSE,
    followed_up_at TIMESTAMP
);

-- Index for user state vectors queries
CREATE INDEX IF NOT EXISTS idx_user_state_vectors_lookup ON user_state_vectors(user_id, language_id, last_updated DESC);

-- Index for RL recommendation history
CREATE INDEX IF NOT EXISTS idx_rl_recommendations_user ON rl_recommendation_history(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_rl_recommendations_strategy ON rl_recommendation_history(strategy, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_rl_recommendations_followup ON rl_recommendation_history(user_id, followed_up, created_at DESC);

-- Index for user_question_history
CREATE INDEX IF NOT EXISTS idx_user_question_history_user ON user_question_history(user_id);
CREATE INDEX IF NOT EXISTS idx_user_question_history_question ON user_question_history(question_id);
CREATE INDEX IF NOT EXISTS idx_user_question_history_unique ON user_question_history(user_id, question_id);

-- Index for learning_paths
CREATE INDEX IF NOT EXISTS idx_learning_paths_user ON learning_paths(user_id, is_active);
CREATE INDEX IF NOT EXISTS idx_learning_paths_language ON learning_paths(language_id);

-- Index for question_reports
CREATE INDEX IF NOT EXISTS idx_question_reports_status ON question_reports(status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_question_reports_question ON question_reports(question_id);

-- Index for user_queries
CREATE INDEX IF NOT EXISTS idx_user_queries_status ON user_queries(status, priority, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_user_queries_user ON user_queries(user_id);

-- Index for admin_logs
CREATE INDEX IF NOT EXISTS idx_admin_logs_admin ON admin_logs(admin_id, created_at DESC);
"""

if __name__ == "__main__":
    print("Creating database tables...")
    
    with engine.connect() as conn:
        # Execute each statement separately
        for statement in SCHEMA.split(';'):
            statement = statement.strip()
            if statement:
                try:
                    conn.execute(text(statement))
                    conn.commit()
                except Exception as e:
                    print(f"Warning: {e}")
    
    print("✅ All tables created successfully")
    print("\nTables:")
    with engine.connect() as conn:
        result = conn.execute(text("SELECT table_name FROM information_schema.tables WHERE table_schema='public' ORDER BY table_name"))
        for row in result:
            print(f"  - {row[0]}")
