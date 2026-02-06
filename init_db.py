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
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 2. Student State (The "Live" Mastery Matrix)
CREATE TABLE IF NOT EXISTS student_state (
    user_id VARCHAR REFERENCES users(id) ON DELETE CASCADE,
    mapping_id VARCHAR NOT NULL,
    language_id VARCHAR NOT NULL,
    mastery_score REAL DEFAULT 0.0, 
    confidence_score REAL DEFAULT 0.0,
    fluency_score REAL DEFAULT 0.0,
    last_practiced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, mapping_id, language_id)
);

-- 3. Question Bank
CREATE TABLE IF NOT EXISTS question_bank (
    id VARCHAR PRIMARY KEY,
    content_hash VARCHAR UNIQUE NOT NULL,
    mapping_id VARCHAR NOT NULL,
    language_id VARCHAR NOT NULL,
    sub_topic VARCHAR,
    difficulty REAL NOT NULL,
    question_data JSON NOT NULL,
    is_verified BOOLEAN DEFAULT 0,
    quality_score REAL DEFAULT 0.5,
    times_used INTEGER DEFAULT 0,
    times_correct INTEGER DEFAULT 0,
    calibrated_difficulty REAL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR DEFAULT 'gemini-1.5-pro'
);

-- 4. User Question History (tracks which questions each user has seen)
CREATE TABLE IF NOT EXISTS user_question_history (
    id VARCHAR PRIMARY KEY,
    user_id VARCHAR NOT NULL,
    question_id VARCHAR REFERENCES question_bank(id) ON DELETE CASCADE,
    session_id VARCHAR,
    was_correct BOOLEAN,
    time_spent_seconds REAL,
    seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 5. Exam Sessions (with Phase 2B: Adaptive Difficulty, Phase 2C: Review Type)
CREATE TABLE IF NOT EXISTS exam_sessions (
    id VARCHAR PRIMARY KEY,
    user_id VARCHAR REFERENCES users(id) ON DELETE CASCADE,
    language_id VARCHAR NOT NULL,
    major_topic_id VARCHAR NOT NULL,
    session_type VARCHAR DEFAULT 'practice',  -- 'practice', 'diagnostic', 'review'
    overall_score REAL NOT NULL,
    difficulty_assigned REAL NOT NULL,
    time_taken_seconds INTEGER NOT NULL,
    rl_action_taken VARCHAR NOT NULL,
    recommended_next_difficulty REAL DEFAULT 0.5,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 6. Exam Details (Individual Question Results)
CREATE TABLE IF NOT EXISTS exam_details (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id VARCHAR REFERENCES exam_sessions(id) ON DELETE CASCADE,
    questions_snapshot JSON NOT NULL,
    recommendations JSON,
    synergy_applied BOOLEAN DEFAULT 0
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_student_state_user ON student_state(user_id);
CREATE INDEX IF NOT EXISTS idx_exam_sessions_user ON exam_sessions(user_id);
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
    current_mastery REAL NOT NULL,
    mastery_at_last_review REAL,
    days_since_last_review INTEGER DEFAULT 0,
    
    -- Scheduling
    next_review_date TIMESTAMP NOT NULL,
    review_interval_days INTEGER NOT NULL,
    review_priority INTEGER DEFAULT 0,
    
    -- Performance tracking
    successful_reviews INTEGER DEFAULT 0,
    failed_reviews INTEGER DEFAULT 0,
    personal_decay_rate REAL DEFAULT 0.02,
    
    -- Timestamps
    last_reviewed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    UNIQUE(user_id, language_id, mapping_id)
);

-- Phase 2C: Indexes for review queries
CREATE INDEX IF NOT EXISTS idx_review_schedule_lookup ON review_schedule(user_id, language_id, next_review_date);
CREATE INDEX IF NOT EXISTS idx_review_schedule_due ON review_schedule(next_review_date);

-- 8. Phase 2D: Error History (Advanced Error Pattern Analysis)
CREATE TABLE IF NOT EXISTS error_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id VARCHAR REFERENCES users(id) ON DELETE CASCADE,
    language_id VARCHAR NOT NULL,
    mapping_id VARCHAR NOT NULL,
    session_id VARCHAR REFERENCES exam_sessions(id) ON DELETE CASCADE,
    question_id VARCHAR NOT NULL,
    
    -- Error details
    error_type VARCHAR NOT NULL,
    error_category VARCHAR NOT NULL,
    severity REAL NOT NULL,
    
    -- Context
    difficulty_tier INTEGER DEFAULT 1,
    is_corrected BOOLEAN DEFAULT 0,
    
    -- Timestamps
    occurred_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
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
    session_snapshot JSON NOT NULL,
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Index for user state vectors queries
CREATE INDEX IF NOT EXISTS idx_user_state_vectors_lookup ON user_state_vectors(user_id, language_id, last_updated DESC);

-- Index for user_question_history
CREATE INDEX IF NOT EXISTS idx_user_question_history_user ON user_question_history(user_id);
CREATE INDEX IF NOT EXISTS idx_user_question_history_question ON user_question_history(question_id);
CREATE INDEX IF NOT EXISTS idx_user_question_history_unique ON user_question_history(user_id, question_id);
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
        result = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"))
        for row in result:
            print(f"  - {row[0]}")
