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
        # JSONB can return dict/list already, or JSON string depending on driver settings.
        if isinstance(questions_raw, dict):
            questions = questions_raw.get('questions', [])
        elif isinstance(questions_raw, list):
            questions = questions_raw
        elif isinstance(questions_raw, str):
            parsed_questions = json.loads(questions_raw)
            if isinstance(parsed_questions, dict):
                questions = parsed_questions.get('questions', [])
            elif isinstance(parsed_questions, list):
                questions = parsed_questions
            else:
                questions = []
        else:
            questions = []
        accuracy = exam_data[3] or 0.0
        time_taken = exam_data[4] or 120
        current_mastery = 0.0  # Will be calculated from questions if needed
        
        # 3. Prepare analysis inputs
        error_summary = {}
        topic_breakdown = {}
        total_expected_time = 0
        code_contexts = []  # NEW: Store wrong answer contexts
        
        for q in questions:
            # Count errors
            if q.get('error_type'):
                error_summary[q['error_type']] = error_summary.get(q['error_type'], 0) + 1
            
            # NEW: Collect wrong answer code contexts
            # Phase 2 Fix (Bug 5): Use field names expected by _build_prompt()
            if not q.get('is_correct') and q.get('error_type'):
                # Find selected and correct options for better context
                options = q.get('options', [])
                selected_opt = next((o for o in options if o.get('id') == q.get('selected_choice')), {})
                correct_opt = next((o for o in options if o.get('is_correct')), {})
                
                code_contexts.append({
                    'error_type': q['error_type'],
                    'question': q.get('question_text', '')[:200],  # 'question' not 'question_text'
                    'code_snippet': q.get('code_snippet', '')[:300] if q.get('code_snippet') else None,
                    'selected_answer': selected_opt.get('text', q.get('selected_choice', ''))[:60],
                    'correct_answer': correct_opt.get('text', q.get('correct_choice', ''))[:60],
                    'why_wrong': q.get('explanation', '')[:100]  # 'why_wrong' not 'option_explanation'
                })
            
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
        
        # 3.5. GATHER CONTEXT for enhanced prompts
        user_id = db.execute(text("SELECT user_id FROM exam_sessions WHERE id = :sid"), {"sid": session_id}).scalar()
        
        # Get language-specific experience level from preferences table
        experience_level = db.execute(text("""
            SELECT experience_level 
            FROM user_language_preferences 
            WHERE user_id = :uid AND language_id = :lang
        """), {"uid": user_id, "lang": language_id}).scalar()
        
        # Fallback to global experience level if not found
        if not experience_level:
            experience_level = db.execute(text("""
                SELECT experience_level FROM users WHERE id = :uid
            """), {"uid": user_id}).scalar() or 'intermediate'
        
        # Get error history (total counts across all sessions)
        # Phase 2 Fix (Bug 3): error_history has no 'count' column - each row is one occurrence
        error_history_rows = db.execute(text("""
            SELECT error_type, COUNT(*) as total_count
            FROM error_history
            WHERE user_id = :uid AND language_id = :lang
            GROUP BY error_type
        """), {"uid": user_id, "lang": language_id}).fetchall()
        error_history = {row[0]: row[1] for row in error_history_rows}
        
        # Get prerequisite status from student_state
        from services.config import get_config
        config = get_config()
        
        # Phase 2 Fix (Bug 2): prerequisite_strength_weights is an array, not a dict
        mapping_id = config.get_mapping_id(language_id, topic_name)
        prereq_list = config.transition_map.get('prerequisite_strength_weights', [])
        
        # Find the matching topic in the array
        topic_prereq_entry = next(
            (entry for entry in prereq_list if entry.get('target_mapping_id') == mapping_id),
            None
        )
        topic_prereqs = topic_prereq_entry.get('prerequisites', {}) if topic_prereq_entry else {}
        
        prereq_status = {}
        prereq_gaps = []
        if topic_prereqs:
            prereq_ids = list(topic_prereqs.keys())
            prereq_rows = db.execute(text("""
                SELECT mapping_id, mastery_score
                FROM student_state
                WHERE user_id = :uid AND language_id = :lang AND mapping_id = ANY(:prereqs)
            """), {"uid": user_id, "lang": language_id, "prereqs": prereq_ids}).fetchall()
            
            for row in prereq_rows:
                prereq_status[row[0]] = row[1]
            
            # Identify gaps (mastery < 0.65)
            for prereq_id, weight in topic_prereqs.items():
                current_mastery = prereq_status.get(prereq_id, 0.0)
                if current_mastery < 0.65:
                    prereq_gaps.append({
                        'topic': prereq_id,
                        'current': current_mastery,
                        'required': 0.65,
                        'weight': weight
                    })
        
        # 4. Prepare error list for detailed explanations
        # Phase 2 Fix (Bug 4): Call generate_error_explanations() to get per-error LLM insights
        error_list = [
            {
                'error_type': err_type,
                'count': err_count,
                'code_context': next((ctx.get('code_snippet', '') for ctx in code_contexts if ctx['error_type'] == err_type), ''),
                'option_explanation': next((ctx.get('why_wrong', '') for ctx in code_contexts if ctx['error_type'] == err_type), '')
            }
            for err_type, err_count in error_summary.items()
        ]

        # 5. Generate analysis with OpenAI GPT-4o-mini (WITH CONTEXT)
        # Run independent LLM calls in parallel to reduce wall-clock latency.
        feedback_service = ExamAnalysisService()
        recommendations_service = ExamAnalysisService()
        error_explanations_service = ExamAnalysisService()

        async def _feedback_call():
            return await asyncio.to_thread(
                feedback_service.generate_feedback,
                topic_name,
                accuracy,
                fluency_ratio,
                current_mastery,
                error_summary,
                topic_acc,
                questions,
                language_id,
                experience_level,
                error_history,
                code_contexts,
                prereq_status
            )

        async def _recommendations_call():
            return await asyncio.to_thread(
                recommendations_service.generate_resource_recommendations,
                topic_name,
                error_summary,
                topic_acc,
                language_id,
                experience_level,
                error_history,
                prereq_gaps
            )

        async def _error_explanations_call():
            if not error_list:
                return {}
            return await asyncio.to_thread(
                error_explanations_service.generate_error_explanations,
                error_list,
                language_id,
                experience_level
            )

        bullets, resources, error_explanations = await asyncio.gather(
            _feedback_call(),
            _recommendations_call(),
            _error_explanations_call()
        )

        recommendations_source = getattr(recommendations_service, 'last_recommendations_source', 'unknown')
        error_patterns_source = getattr(error_explanations_service, 'last_error_explanations_source', 'unknown') if error_list else 'none'

        recommendations_payload = {
            "resources": resources,
            "error_patterns": [
                {"error_type": k, "count": v} for k, v in error_summary.items()
            ],
            "error_explanations": error_explanations,  # NEW: Per-error LLM explanations
            "topic_breakdown": topic_acc,
            "meta": {
                "recommendations_source": recommendations_source,
                "error_patterns_source": error_patterns_source
            }
        }
        
        # 5. Save analysis
        db.execute(text("""
            UPDATE exam_details 
            SET 
                analysis_status = 'completed',
                analysis_bullets = :bullets,
                recommendations = :recommendations,
                analysis_generated_at = :now,
                analysis_error = NULL
            WHERE session_id = :sid
        """), {
            "bullets": bullets,
            "recommendations": json.dumps(recommendations_payload),
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
