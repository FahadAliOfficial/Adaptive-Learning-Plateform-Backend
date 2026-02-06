"""Database schema verification script"""
from database import engine
from sqlalchemy import text, inspect

def verify_schema():
    print("="*80)
    print("DATABASE SCHEMA VERIFICATION")
    print("="*80)
    
    with engine.connect() as conn:
        # Get all tables
        result = conn.execute(text("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema='public' 
            ORDER BY table_name
        """))
        tables = [row[0] for row in result]
        
        print(f"\n📋 Total Tables: {len(tables)}")
        print("-" * 80)
        
        expected_tables = [
            'users', 'student_state', 'question_bank', 'user_question_history',
            'exam_sessions', 'exam_details', 'review_schedule', 'error_history',
            'user_state_vectors', 'learning_paths', 'question_reports', 'user_queries',
            'admin_logs', 'notification_preferences', 'rl_recommendation_history'
        ]
        
        for table in tables:
            # Get column count for each table
            col_result = conn.execute(text(f"""
                SELECT COUNT(*) 
                FROM information_schema.columns 
                WHERE table_name='{table}' AND table_schema='public'
            """))
            col_count = col_result.scalar()
            
            # Check if expected
            status = "✅" if table in expected_tables else "⚠️  NEW"
            print(f"{status} {table:<35} ({col_count} columns)")
        
        print("-" * 80)
        
        # Check for missing tables
        missing = set(expected_tables) - set(tables)
        if missing:
            print(f"\n❌ Missing Tables: {', '.join(missing)}")
        else:
            print(f"\n✅ All {len(expected_tables)} expected tables exist")
        
        # Verify exam_details has migration columns
        print("\n" + "="*80)
        print("EXAM_DETAILS TABLE - MIGRATION VERIFICATION")
        print("="*80)
        
        exam_cols = conn.execute(text("""
            SELECT column_name, data_type, column_default
            FROM information_schema.columns
            WHERE table_name='exam_details' AND table_schema='public'
            ORDER BY ordinal_position
        """))
        
        migration_cols = {
            'analysis_status': False,
            'analysis_bullets': False, 
            'analysis_generated_at': False,
            'analysis_error': False
        }
        
        print("\nColumns:")
        for row in exam_cols:
            col_name, data_type, default = row
            print(f"  • {col_name:<30} {data_type:<20} {default or ''}")
            
            if col_name in migration_cols:
                migration_cols[col_name] = True
        
        print("\n" + "-" * 80)
        print("Migration Columns Status:")
        for col, exists in migration_cols.items():
            status = "✅" if exists else "❌ MISSING"
            print(f"  {status} {col}")
        
        all_migration_cols_exist = all(migration_cols.values())
        
        # Verify question_reports table (needed for Item 18)
        print("\n" + "="*80)
        print("QUESTION_REPORTS TABLE - ITEM 18 VERIFICATION")
        print("="*80)
        
        if 'question_reports' in tables:
            report_cols = conn.execute(text("""
                SELECT column_name, data_type
                FROM information_schema.columns
                WHERE table_name='question_reports' AND table_schema='public'
                ORDER BY ordinal_position
            """))
            
            print("\nColumns:")
            report_col_names = []
            for row in report_cols:
                col_name, data_type = row
                print(f"  • {col_name:<30} {data_type}")
                report_col_names.append(col_name)
            
            expected_report_cols = ['id', 'question_id', 'user_id', 'report_type', 'description', 
                                   'status', 'created_at', 'reviewed_by', 'reviewed_at', 'resolution_notes']
            
            missing_report_cols = set(expected_report_cols) - set(report_col_names)
            if missing_report_cols:
                print(f"\n❌ Missing columns: {', '.join(missing_report_cols)}")
            else:
                print(f"\n✅ All {len(expected_report_cols)} expected columns exist")
        else:
            print("\n❌ question_reports table does NOT exist")
        
        # Final summary
        print("\n" + "="*80)
        print("VERIFICATION SUMMARY")
        print("="*80)
        
        issues = []
        
        if missing:
            issues.append(f"Missing {len(missing)} tables: {', '.join(missing)}")
        
        if not all_migration_cols_exist:
            missing_migration = [col for col, exists in migration_cols.items() if not exists]
            issues.append(f"exam_details missing columns: {', '.join(missing_migration)}")
        
        if 'question_reports' not in tables:
            issues.append("question_reports table missing (required for Item 18)")
        
        if issues:
            print("\n❌ ISSUES FOUND:")
            for i, issue in enumerate(issues, 1):
                print(f"  {i}. {issue}")
            print("\n⚠️  Database needs to be recreated with init_db.py")
        else:
            print("\n✅ DATABASE SCHEMA IS CORRECT")
            print(f"✅ All {len(expected_tables)} tables exist")
            print(f"✅ All migration columns present in exam_details")
            print(f"✅ question_reports table ready for Item 18")
            print(f"\n✨ Total: {len(tables)} tables, schema verified successfully")

if __name__ == "__main__":
    verify_schema()
