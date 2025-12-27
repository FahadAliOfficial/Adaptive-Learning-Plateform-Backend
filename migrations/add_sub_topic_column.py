"""
Database Migration: Add sub_topic column to question_bank table

This migration adds sub_topic tracking for granular analytics and Phase 2B support.

Run this ONCE before using the new analytics features.
"""
import sys
import os

# Add parent directory to path to import database module
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import engine
from sqlalchemy import text


def migrate():
    """Add sub_topic column to question_bank table."""
    
    print("🔧 Starting migration: add_sub_topic_column")
    
    try:
        with engine.connect() as conn:
            # Check if column already exists (SQLite-compatible check)
            check_query = text("""
                SELECT COUNT(*) as count
                FROM pragma_table_info('question_bank')
                WHERE name = 'sub_topic'
            """)
            
            result = conn.execute(check_query).fetchone()
            
            if result and result[0] > 0:
                print("✅ Column 'sub_topic' already exists. Skipping migration.")
                return True
            
            # Add the column
            alter_query = text("ALTER TABLE question_bank ADD COLUMN sub_topic VARCHAR(100)")
            conn.execute(alter_query)
            conn.commit()
            
            print("✅ Successfully added 'sub_topic' column to question_bank")
            
            # Verify the column was added
            verify_query = text("""
                SELECT COUNT(*) as count
                FROM pragma_table_info('question_bank')
                WHERE name = 'sub_topic'
            """)
            
            verify = conn.execute(verify_query).fetchone()
            
            if verify and verify[0] > 0:
                print("✅ Migration verified successfully")
                return True
            else:
                print("❌ Migration verification failed")
                return False
                
    except Exception as e:
        print(f"❌ Migration failed: {e}")
        return False


def rollback():
    """Remove sub_topic column (rollback migration)."""
    
    print("🔄 Rolling back migration: add_sub_topic_column")
    
    try:
        with engine.connect() as conn:
            # SQLite doesn't support DROP COLUMN directly
            # Would need to recreate table without the column
            print("⚠️ SQLite doesn't support DROP COLUMN")
            print("⚠️ Manual rollback required: recreate table without sub_topic")
            return False
            
    except Exception as e:
        print(f"❌ Rollback failed: {e}")
        return False


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "rollback":
        success = rollback()
    else:
        success = migrate()
    
    if success:
        print("\n✅ Migration completed successfully!")
        sys.exit(0)
    else:
        print("\n❌ Migration failed!")
        sys.exit(1)
