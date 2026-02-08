"""
Run Multi-Language Support Migration
"""
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import text, create_engine
from database import DATABASE_URL

def run_migration():
    """Execute migration SQL"""
    engine = create_engine(DATABASE_URL)
    
    sql_commands = [
        """
        ALTER TABLE users 
        ADD COLUMN IF NOT EXISTS primary_language VARCHAR;
        """,
        """
        ALTER TABLE users 
        ADD COLUMN IF NOT EXISTS languages_learning JSONB DEFAULT '[]'::jsonb;
        """,
        """
        UPDATE users 
        SET 
            primary_language = last_active_language,
            languages_learning = CASE 
                WHEN last_active_language IS NOT NULL 
                THEN jsonb_build_array(last_active_language)
                ELSE '[]'::jsonb
            END
        WHERE primary_language IS NULL;
        """
    ]
    
    with engine.connect() as conn:
        with conn.begin():
            for sql in sql_commands:
                print(f"Executing: {sql.strip()[:50]}...")
                conn.execute(text(sql))
            print("✅ Migration completed successfully!")

if __name__ == "__main__":
    print("🔄 Running multi-language support migration...")
    try:
        run_migration()
    except Exception as e:
        print(f"❌ Migration failed: {e}")
        sys.exit(1)
