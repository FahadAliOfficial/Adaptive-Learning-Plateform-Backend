"""Quick DB integration test"""
from database import SessionLocal, engine
from sqlalchemy import text
import uuid

def test_all_tables():
    """Test CRUD on all tables"""
    db = SessionLocal()
    try:
        # Test users table
        user_id = str(uuid.uuid4())
        db.execute(text("""
            INSERT INTO users (id, email, password_hash) 
            VALUES (:id, 'test@test.com', 'hash123')
        """), {"id": user_id})
        
        # Test student_state
        db.execute(text("""
            INSERT INTO student_state (user_id, mapping_id, language_id, mastery_score, fluency_score, confidence_score)
            VALUES (:u, 'UNIV_LOOP', 'python_3', 0.5, 1.0, 0.5)
        """), {"u": user_id})
        
        # Test question_bank
        q_id = str(uuid.uuid4())
        db.execute(text("""
            INSERT INTO question_bank (id, content_hash, mapping_id, language_id, difficulty, question_data, sub_topic, quality_score, times_used, times_correct, created_by)
            VALUES (:id, 'hash1', 'UNIV_LOOP', 'python_3', 0.5, '{}', 'for_loops', 0.8, 0, 0, 'test')
        """), {"id": q_id})
        
        # Test user_question_history
        hist_id = str(uuid.uuid4())
        db.execute(text("""
            INSERT INTO user_question_history (id, user_id, question_id, was_correct, time_spent_seconds)
            VALUES (:id, :u, :q, 1, 30.5)
        """), {"id": hist_id, "u": user_id, "q": q_id})
        
        # Test exam_sessions
        session_id = str(uuid.uuid4())
        db.execute(text("""
            INSERT INTO exam_sessions (id, user_id, language_id, major_topic_id, overall_score, difficulty_assigned, time_taken_seconds, rl_action_taken, recommended_next_difficulty)
            VALUES (:id, :u, 'python_3', 'PY_LOOP', 0.8, 0.5, 300, 'TEST', 0.6)
        """), {"id": session_id, "u": user_id})
        
        # Test exam_details
        db.execute(text("""
            INSERT INTO exam_details (session_id, questions_snapshot, recommendations, synergy_applied)
            VALUES (:s, '{"questions": []}', '{}', 0)
        """), {"s": session_id})
        
        # Test review_schedule
        review_id = str(uuid.uuid4())
        db.execute(text("""
            INSERT INTO review_schedule (id, user_id, language_id, mapping_id, current_mastery, next_review_date, review_interval_days, review_priority, personal_decay_rate)
            VALUES (:id, :u, 'python_3', 'UNIV_LOOP', 0.7, datetime('now', '+7 days'), 7, 3, 0.02)
        """), {"id": review_id, "u": user_id})
        
        # Test error_history
        db.execute(text("""
            INSERT INTO error_history (user_id, language_id, mapping_id, session_id, question_id, error_type, error_category, severity, difficulty_tier)
            VALUES (:u, 'python_3', 'UNIV_LOOP', :s, :q, 'OFF_BY_ONE', 'LOOP_ERRORS', 0.5, 1)
        """), {"u": user_id, "s": session_id, "q": q_id})
        
        # Test user_state_vectors
        vector_id = str(uuid.uuid4())
        db.execute(text("""
            INSERT INTO user_state_vectors (id, user_id, language_id, session_snapshot)
            VALUES (:id, :u, 'python_3', '{"questions": []}')
        """), {"id": vector_id, "u": user_id})
        
        db.commit()
        
        # Read back
        result = db.execute(text("SELECT COUNT(*) FROM users WHERE id = :u"), {"u": user_id}).scalar()
        assert result == 1
        
        # Cleanup
        db.execute(text("DELETE FROM user_state_vectors WHERE user_id = :u"), {"u": user_id})
        db.execute(text("DELETE FROM error_history WHERE user_id = :u"), {"u": user_id})
        db.execute(text("DELETE FROM exam_details WHERE session_id = :s"), {"s": session_id})
        db.execute(text("DELETE FROM exam_sessions WHERE user_id = :u"), {"u": user_id})
        db.execute(text("DELETE FROM review_schedule WHERE user_id = :u"), {"u": user_id})
        db.execute(text("DELETE FROM user_question_history WHERE user_id = :u"), {"u": user_id})
        db.execute(text("DELETE FROM question_bank WHERE id = :q"), {"q": q_id})
        db.execute(text("DELETE FROM student_state WHERE user_id = :u"), {"u": user_id})
        db.execute(text("DELETE FROM users WHERE id = :u"), {"u": user_id})
        db.commit()
        
        print("✓ All tables CRUD OK")
        return True
    except Exception as e:
        print(f"✗ Error: {e}")
        db.rollback()
        return False
    finally:
        db.close()

if __name__ == "__main__":
    test_all_tables()
