"""
Migration: Create question_reports table for student feedback on questions

Allows students to report issues with questions during or after exams.
Admins can resolve/dismiss reports from admin dashboard.
"""

import sys
from sqlalchemy import text
from database import engine

def create_question_reports_table():
    """Create question_reports table with proper constraints and indexes"""
    
    with engine.connect() as conn:
        # Check if table exists
        check_query = text("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_name = 'question_reports'
            )
        """)
        
        exists = conn.execute(check_query).scalar()
        
        if exists:
            print("✓ question_reports table already exists")
            return
        
        # Create table
        create_table = text("""
            CREATE TABLE question_reports (
                id SERIAL PRIMARY KEY,
                question_id VARCHAR(255) NOT NULL,
                reporter_user_id VARCHAR(255) NOT NULL,
                session_id VARCHAR(255),
                report_type VARCHAR(50) NOT NULL,
                description TEXT NOT NULL,
                status VARCHAR(20) NOT NULL DEFAULT 'pending',
                resolved_by VARCHAR(255),
                created_at TIMESTAMP DEFAULT NOW(),
                resolved_at TIMESTAMP,
                
                CONSTRAINT fk_question FOREIGN KEY (question_id) 
                    REFERENCES question_bank(id) ON DELETE CASCADE,
                CONSTRAINT fk_reporter FOREIGN KEY (reporter_user_id) 
                    REFERENCES users(id) ON DELETE CASCADE,
                CONSTRAINT fk_session FOREIGN KEY (session_id) 
                    REFERENCES exam_sessions(id) ON DELETE SET NULL,
                CONSTRAINT fk_resolver FOREIGN KEY (resolved_by) 
                    REFERENCES users(id) ON DELETE SET NULL,
                
                CONSTRAINT valid_report_type CHECK (
                    report_type IN ('incorrect_answer', 'missing_correct', 'confusing_wording', 
                                   'explanation_mismatch', 'other')
                ),
                CONSTRAINT valid_status CHECK (
                    status IN ('pending', 'resolved', 'dismissed')
                ),
                
                CONSTRAINT unique_report_per_user_question UNIQUE (question_id, reporter_user_id)
            )
        """)
        
        conn.execute(create_table)
        conn.commit()
        print("✓ Created question_reports table")
        
        # Create indexes for common queries
        indexes = [
            "CREATE INDEX idx_reports_status ON question_reports(status, created_at DESC)",
            "CREATE INDEX idx_reports_question ON question_reports(question_id)",
            "CREATE INDEX idx_reports_reporter ON question_reports(reporter_user_id)",
            "CREATE INDEX idx_reports_created ON question_reports(created_at DESC)"
        ]
        
        for idx_query in indexes:
            conn.execute(text(idx_query))
            conn.commit()
        
        print("✓ Created indexes on question_reports")
        
        # Verify table creation
        verify = text("""
            SELECT COUNT(*) FROM information_schema.columns 
            WHERE table_name = 'question_reports'
        """)
        col_count = conn.execute(verify).scalar()
        print(f"✓ Table created with {col_count} columns")

if __name__ == "__main__":
    try:
        print("Creating question_reports table...")
        create_question_reports_table()
        print("\n✅ Migration completed successfully")
    except Exception as e:
        print(f"\n❌ Migration failed: {e}")
        sys.exit(1)
