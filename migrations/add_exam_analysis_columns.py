"""
Migration: Add exam analysis fields to exam_details table.
Also changes question_bank.created_by default to 'gpt-4o-mini'.

Run this after updating to OpenAI version.
"""
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from sqlalchemy import text
from database import SessionLocal

def migrate():
    """Add analysis columns to exam_details table"""
    db = SessionLocal()
    
    try:
        print("🔧 Adding exam analysis columns to exam_details table...")
        
        # Add analysis columns
        db.execute(text("""
            ALTER TABLE exam_details 
            ADD COLUMN IF NOT EXISTS analysis_status VARCHAR(20) DEFAULT 'pending',
            ADD COLUMN IF NOT EXISTS analysis_bullets TEXT[],
            ADD COLUMN IF NOT EXISTS analysis_generated_at TIMESTAMP,
            ADD COLUMN IF NOT EXISTS analysis_error TEXT;
        """))
        
        db.commit()
        print("✅ Migration completed successfully!")
        print("   - Added analysis_status column")
        print("   - Added analysis_bullets column")
        print("   - Added analysis_generated_at column")
        print("   - Added analysis_error column")
        
    except Exception as e:
        db.rollback()
        print(f"❌ Migration failed: {e}")
        raise
    
    finally:
        db.close()


if __name__ == "__main__":
    migrate()
