"""
Background Tasks - Async exam analysis generation.
Uses OpenAI GPT-4o-mini to generate feedback after exam submission.
"""
import asyncio
from sqlalchemy import text
from datetime import datetime
from services.exam_analysis_service import ExamAnalysisService
import logging
import json

logger = logging.getLogger(__name__)


async def generate_exam_analysis_task(
    session_id: str,
    db_connection_string: str  # Pass connection, not Session
):
    """
    Background task to generate exam analysis.
    Runs async after exam submission completes.
    
    Args:
        session_id: Exam session UUID
        db_connection_string: Database connection string for new session
    """
    from database import SessionLocal
    db = SessionLocal()
    
    try:
        # 1. Mark as generating
        db.execute(text("""
            UPDATE exam_details 
            SET analysis_status = 'generating'
            WHERE session_id = :sid
        """), {"sid": session_id})
        db.commit()
        
        logger.info(f"[Analysis] Starting generation for session {session_id[:8]}...")
        
        # 2. Fetch exam data (simplified - no curriculum_mapping dependency)
        exam_data = db.execute(text("""
            SELECT 
                es.language_id,
                es.major_topic_id,
                ed.questions_snapshot,
                es.overall_score,
                es.time_taken_seconds
            FROM exam_sessions es
            JOIN exam_details ed ON ed.session_id = es.id
            WHERE es.id = :sid
        """), {"sid": session_id}).fetchone()
        
        if not exam_data:
            raise ValueError(f"Session {session_id} not found")
        
        language_id = exam_data[0]
        topic_name = exam_data[1]
        questions_raw = exam_data[2]
        # JSONB returns as dict/list already, no need for json.loads()
        if isinstance(questions_raw, list):
            questions = questions_raw
        elif isinstance(questions_raw, str):
            questions = json.loads(questions_raw)
        else:
            questions = []
        accuracy = exam_data[3] or 0.0
        time_taken = exam_data[4] or 120
        current_mastery = 0.0  # Will be calculated from questions if needed
        
        # 3. Prepare analysis inputs
        error_summary = {}
        topic_breakdown = {}
        total_expected_time = 0
        
        for q in questions:
            # Count errors
            if q.get('error_type'):
                error_summary[q['error_type']] = error_summary.get(q['error_type'], 0) + 1
            
            # Track topic accuracy
            sub_topic = q.get('sub_topic', 'Unknown')
            if sub_topic not in topic_breakdown:
                topic_breakdown[sub_topic] = {'correct': 0, 'total': 0}
            topic_breakdown[sub_topic]['total'] += 1
            if q.get('is_correct'):
                topic_breakdown[sub_topic]['correct'] += 1
            
            # Track expected time
            total_expected_time += q.get('expected_time', 60)
        
        # Calculate topic accuracies
        topic_acc = {
            topic: data['correct'] / data['total']
            for topic, data in topic_breakdown.items()
        }
        
        # Calculate fluency ratio
        fluency_ratio = total_expected_time / max(time_taken, 1)
        
        # 4. Generate analysis with OpenAI GPT-4o-mini
        analysis_service = ExamAnalysisService()
        
        bullets = analysis_service.generate_feedback(
            topic_name=topic_name,
            accuracy=accuracy,
            fluency_ratio=fluency_ratio,
            current_mastery=current_mastery,
            error_summary=error_summary,
            topic_breakdown=topic_acc,
            results=questions
        )
        
        # 5. Save analysis
        db.execute(text("""
            UPDATE exam_details 
            SET 
                analysis_status = 'completed',
                analysis_bullets = :bullets,
                analysis_generated_at = :now
            WHERE session_id = :sid
        """), {
            "bullets": bullets,
            "now": datetime.now(),
            "sid": session_id
        })
        db.commit()
        
        logger.info(f"✅ Analysis completed for session {session_id[:8]}... - {len(bullets)} bullets")
        
    except Exception as e:
        logger.error(f"❌ Analysis failed for session {session_id}: {e}")
        db.rollback()  # Rollback failed transaction before updating
        db.execute(text("""
            UPDATE exam_details 
            SET 
                analysis_status = 'failed',
                analysis_error = :error
            WHERE session_id = :sid
        """), {"error": str(e)[:500], "sid": session_id})  # Truncate error to 500 chars
        db.commit()
        
    finally:
        db.close()
