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
    difficulty REAL NOT NULL,
    question_data JSON NOT NULL,
    is_verified BOOLEAN DEFAULT 0,
    use_count INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 4. User Seen Questions
CREATE TABLE IF NOT EXISTS user_seen_questions (
    user_id VARCHAR REFERENCES users(id) ON DELETE CASCADE,
    question_id VARCHAR REFERENCES question_bank(id) ON DELETE CASCADE,
    seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, question_id)
);

-- 5. Exam Sessions (with Phase 2B: Adaptive Difficulty)
CREATE TABLE IF NOT EXISTS exam_sessions (
    id VARCHAR PRIMARY KEY,
    user_id VARCHAR REFERENCES users(id) ON DELETE CASCADE,
    language_id VARCHAR NOT NULL,
    major_topic_id VARCHAR NOT NULL,
    session_type VARCHAR DEFAULT 'practice',
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
