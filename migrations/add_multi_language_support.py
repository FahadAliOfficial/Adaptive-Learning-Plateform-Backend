"""
Migration: Add Multi-Language Learning Support
Adds primary_language and languages_learning fields to users table

Run this SQL manually in your PostgreSQL database:
"""

SQL_UPGRADE = """
-- Add primary_language column
ALTER TABLE users 
ADD COLUMN IF NOT EXISTS primary_language VARCHAR;

-- Add languages_learning JSONB array column
ALTER TABLE users 
ADD COLUMN IF NOT EXISTS languages_learning JSONB DEFAULT '[]'::jsonb;

-- Migrate existing last_active_language to primary_language and languages_learning
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

SQL_DOWNGRADE = """
-- Remove multi-language support columns
ALTER TABLE users 
DROP COLUMN IF EXISTS primary_language,
DROP COLUMN IF EXISTS languages_learning;
"""

print("=== Multi-Language Support Migration ===")
print("\nTo apply this migration, run the following SQL in your PostgreSQL database:\n")
print(SQL_UPGRADE)
print("\n=== To rollback, run: ===\n")
print(SQL_DOWNGRADE)
