"""
Admin Router - Handles administrative endpoints for user and question management.

Provides endpoints for admin users to manage platform users, questions, and view analytics.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import text, func, String, cast, or_
from typing import Optional, List, Dict
import hashlib
import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from database import get_db
from services.user_service import UserService
from services.config import get_config
from models.question_bank import QuestionBank, UserQuestionHistory
from services.schemas import (
    AdminUserListResponse,
    AdminUserStatusUpdateRequest,
    AdminUserStatusUpdateResponse,
    AdminUserUpdateRequest,
    AdminUserUpdateResponse,
    AdminPasswordResetRequest,
    AdminPasswordResetResponse,
    AdminUserAnalytics,
    AdminQuestion,
    AdminQuestionListResponse,
    AdminQuestionUpdateRequest,
    AdminQuestionUpdateResponse,
    AdminQuestionDeleteResponse,
    AdminBulkActionRequest,
    AdminBulkActionResponse,
    AdminQuestionAnalytics,
    AdminLowQualityQuestionsResponse,
    AdminHighFailureQuestion,
    AdminHighFailureQuestionsResponse,
    AdminMostReportedQuestion,
    AdminMostReportedQuestionsResponse,
    AdminConceptTimeStat,
    AdminConceptTimeStatsResponse,
    AdminErrorPatternTrend,
    AdminErrorPatternTrendsResponse
)
from services.auth import get_current_admin_user

router = APIRouter(prefix="/api/admin", tags=["Admin"])


def _validate_window_days(window_days: int) -> int:
    if window_days < 1 or window_days > 3650:
        raise HTTPException(status_code=400, detail="window_days must be between 1 and 3650")
    return window_days


def _get_concept_name(mapping_id: str) -> str:
    try:
        config = get_config()
        topic_info = config.mapping_to_topics.get(mapping_id, {})
        for language_payload in topic_info.values():
            topic_name = language_payload.get("name")
            if topic_name:
                return topic_name
    except Exception:
        pass

    return mapping_id


def _resolve_mapping_id(language_id: str, major_topic_id: str) -> str:
    try:
        return get_config().get_mapping_id(language_id, major_topic_id)
    except Exception:
        return major_topic_id


def _extract_question_text(question_data: object) -> str:
    if isinstance(question_data, dict):
        return str(question_data.get("question_text", ""))
    return ""


def _get_question_reports_issue_column(db: Session) -> Optional[str]:
    """Resolve issue column name across legacy/new question_reports schemas."""
    columns = set()

    try:
        rows = db.execute(text("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'question_reports'
        """)).fetchall()
        columns = {str(row[0]) for row in rows if row and row[0]}
    except Exception:
        columns = set()

    if not columns:
        try:
            pragma_rows = db.execute(text("PRAGMA table_info(question_reports)")).mappings().all()
            columns = {str(row.get("name")) for row in pragma_rows if row.get("name")}
        except Exception:
            columns = set()

    if "report_type" in columns:
        return "report_type"
    if "report_reason" in columns:
        return "report_reason"
    return None


@router.get("/users", response_model=AdminUserListResponse)
async def get_all_users(
    search: Optional[str] = Query(None, description="Search by email or name"),
    status: Optional[str] = Query("all", description="Filter by status: all, active, inactive, suspended"),
    current_admin: dict = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
):
    """
    List all users with filtering and search capabilities.
    
    **Use Case:** Admin dashboard user management page
    
    **Example:**
    GET /api/admin/users?search=john&status=active
    
    **Returns:**
    - List of users with calculated status, session count, and mastery
    - User statistics (total, active, inactive, suspended counts)
    
    **Requires:** Admin authentication
    """
    try:
        user_service = UserService(db)
        result = user_service.get_all_users_admin(
            search_query=search,
            status_filter=status
        )
        
        return AdminUserListResponse(
            users=result["users"],
            total_count=result["total_count"],
            active_count=result["active_count"],
            inactive_count=result["inactive_count"],
            suspended_count=result["suspended_count"]
        )
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to retrieve users: {str(e)}")


@router.patch("/users/{user_id}/status", response_model=AdminUserStatusUpdateResponse)
async def update_user_status(
    user_id: str,
    request: AdminUserStatusUpdateRequest,
    current_admin: dict = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
):
    """
    Update a user's status (active, inactive, suspended).
    
    **Use Case:** Admin suspending or activating user accounts
    
    **Example:**
    PATCH /api/admin/users/123e4567-e89b-12d3-a456-426614174000/status
    Body: {"status": "suspended"}
    
    **Returns:**
    - Success confirmation
    - Updated user data
    
    **Requires:** Admin authentication
    """
    try:
        user_service = UserService(db)
        updated_user = user_service.update_user_status_admin(user_id, request.status)
        
        status_messages = {
            "active": "User has been activated successfully",
            "inactive": "User has been marked as inactive",
            "suspended": "User has been suspended successfully"
        }
        
        return AdminUserStatusUpdateResponse(
            message=status_messages.get(request.status, f"User status updated to {request.status}"),
            updated_user=updated_user
        )
    
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update user status: {str(e)}")

# ==================== QUESTION BANK MANAGEMENT ====================

@router.get("/questions", response_model=AdminQuestionListResponse)
async def get_all_questions(
    language_id: Optional[str] = Query(None, description="Filter by language"),
    mapping_id: Optional[str] = Query(None, description="Filter by curriculum topic"),
    is_verified: Optional[bool] = Query(None, description="Filter by verification status"),
    min_quality: Optional[float] = Query(None, ge=0.0, le=1.0, description="Minimum quality score"),
    max_difficulty: Optional[float] = Query(None, ge=0.0, le=1.0, description="Maximum difficulty"),
    min_usage: Optional[int] = Query(None, ge=0, description="Minimum usage count"),
    search: Optional[str] = Query(None, description="Search in question text"),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
    current_admin: dict = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
):
    """
    Browse all questions with advanced filtering.
    
    **Use Case:** Admin question bank management page - browse and filter all questions
    
    **Example:**
    GET /api/admin/questions?language_id=python_3&is_verified=true&page=1&limit=20
    
    **Returns:**
    - Paginated list of questions with full metadata
    - Total, verified, and unverified counts
    
    **Requires:** Admin authentication
    """
    try:
        # Build query with filters
        query = db.query(QuestionBank)
        
        if language_id:
            query = query.filter(QuestionBank.language_id == language_id)
        
        if mapping_id:
            query = query.filter(QuestionBank.mapping_id == mapping_id)
        
        if is_verified is not None:
            query = query.filter(QuestionBank.is_verified == is_verified)
        
        if min_quality is not None:
            query = query.filter(QuestionBank.quality_score >= min_quality)
        
        if max_difficulty is not None:
            query = query.filter(QuestionBank.difficulty <= max_difficulty)
        
        if min_usage is not None:
            query = query.filter(QuestionBank.times_used >= min_usage)
        
        if search:
            # Search in question_data JSONB field AND by question ID
            search_pattern = f"%{search}%"
            query = query.filter(
                or_(
                    # Search in question ID
                    QuestionBank.id.ilike(search_pattern),
                    # Search in question text within JSONB
                    cast(QuestionBank.question_data, String).ilike(search_pattern)
                )
            )
        
        # Get total count
        total_count = query.count()
        
        # Get verified/unverified counts from the FILTERED query
        # Clone the query to avoid modifying the original
        verified_count = query.filter(QuestionBank.is_verified == True).count()
        unverified_count = query.filter(QuestionBank.is_verified == False).count()
        
        # Paginate
        offset = (page - 1) * limit
        questions = query.order_by(
            QuestionBank.created_at.desc()
        ).offset(offset).limit(limit).all()
        
        # Convert to response format
        question_list = [
            AdminQuestion(
                id=q.id,
                language_id=q.language_id,
                mapping_id=q.mapping_id,
                sub_topic=q.sub_topic,
                difficulty=q.difficulty,
                question_data=q.question_data,
                content_hash=q.content_hash,
                is_verified=q.is_verified,
                quality_score=q.quality_score,
                times_used=q.times_used,
                times_correct=q.times_correct,
                calibrated_difficulty=q.calibrated_difficulty,
                created_at=q.created_at.isoformat() if q.created_at else "",
                created_by=q.created_by,
                review_notes=getattr(q, 'review_notes', None)
            )
            for q in questions
        ]
        
        return AdminQuestionListResponse(
            questions=question_list,
            total_count=total_count,
            verified_count=verified_count,
            unverified_count=unverified_count,
            page=page,
            limit=limit
        )
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to retrieve questions: {str(e)}")


@router.get("/questions/low-quality", response_model=AdminLowQualityQuestionsResponse)
async def get_low_quality_questions(
    limit: int = Query(50, ge=1, le=200, description="Maximum questions to return"),
    current_admin: dict = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
):
    """
    Get questions that need review based on quality criteria.
    
    **Criteria:**
    - Quality score < 0.5
    - Accuracy rate < 30% (if used enough times)
    - Very high or very low accuracy (possible issue)
    
    **Use Case:** Admin quality assurance - identify problematic questions
    
    **Example:**
    GET /api/admin/questions/low-quality?limit=50
    
    **Returns:**
    - List of low-quality questions
    - Criteria used for identification
    
    **Requires:** Admin authentication
    """
    try:
        # Find questions with low quality score
        low_quality_questions = db.query(QuestionBank).filter(
            QuestionBank.quality_score < 0.5
        ).all()
        
        # Find questions with poor accuracy (used at least 10 times)
        poor_accuracy_questions = db.query(QuestionBank).filter(
            QuestionBank.times_used >= 10,
            (QuestionBank.times_correct * 1.0 / QuestionBank.times_used) < 0.3
        ).all()
        
        # Combine and deduplicate
        all_low_quality = {q.id: q for q in low_quality_questions}
        for q in poor_accuracy_questions:
            all_low_quality[q.id] = q
        
        questions_list = list(all_low_quality.values())[:limit]
        
        # Convert to response format
        question_responses = [
            AdminQuestion(
                id=q.id,
                language_id=q.language_id,
                mapping_id=q.mapping_id,
                sub_topic=q.sub_topic,
                difficulty=q.difficulty,
                question_data=q.question_data,
                content_hash=q.content_hash,
                is_verified=q.is_verified,
                quality_score=q.quality_score,
                times_used=q.times_used,
                times_correct=q.times_correct,
                calibrated_difficulty=q.calibrated_difficulty,
                created_at=q.created_at.isoformat() if q.created_at else "",
                created_by=q.created_by,
                review_notes=getattr(q, 'review_notes', None)
            )
            for q in questions_list
        ]
        
        return AdminLowQualityQuestionsResponse(
            questions=question_responses,
            total_count=len(question_responses),
            criteria={
                "low_quality_score": "< 0.5",
                "poor_accuracy": "< 30% (min 10 uses)",
                "suspicious_accuracy": "> 95% or < 5% (min 20 uses)"
            }
        )
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to retrieve low-quality questions: {str(e)}")


@router.get("/questions/{question_id}", response_model=AdminQuestion)
async def get_question_by_id(
    question_id: str,
    current_admin: dict = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
):
    """
    Get a single question by ID.
    
    **Use Case:** Admin viewing/editing a specific question from reports or analytics
    
    **Example:**
    GET /api/admin/questions/123e4567-e89b-12d3-a456-426614174000
    
    **Returns:**
    - Complete question data including question_data JSONB
    
    **Requires:** Admin authentication
    """
    try:
        question = db.query(QuestionBank).filter(QuestionBank.id == question_id).first()
        
        if not question:
            raise ValueError(f"Question {question_id} not found")
        
        return AdminQuestion(
            id=question.id,
            language_id=question.language_id,
            mapping_id=question.mapping_id,
            sub_topic=question.sub_topic,
            difficulty=question.difficulty,
            question_data=question.question_data,
            content_hash=question.content_hash,
            is_verified=question.is_verified,
            quality_score=question.quality_score,
            times_used=question.times_used,
            times_correct=question.times_correct,
            calibrated_difficulty=question.calibrated_difficulty,
            created_at=question.created_at.isoformat() if question.created_at else "",
            created_by=question.created_by,
            review_notes=getattr(question, 'review_notes', None)
        )
    
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to retrieve question: {str(e)}")


@router.patch("/questions/{question_id}", response_model=AdminQuestionUpdateResponse)
async def update_question(
    question_id: str,
    request: AdminQuestionUpdateRequest,
    current_admin: dict = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
):
    """
    Update question content and metadata.
    
    **Use Case:** Admin editing question text, options, difficulty, or quality score
    
    **Example:**
    PATCH /api/admin/questions/123e4567-e89b-12d3-a456-426614174000
    Body: {"difficulty": 0.7, "quality_score": 0.9}
    
    **Returns:**
    - Success confirmation
    - Updated question data
    
    **Requires:** Admin authentication
    """
    try:
        from services.content_engine.jsonl_backup import JSONLBackup
        
        question = db.query(QuestionBank).filter(QuestionBank.id == question_id).first()
        
        if not question:
            raise ValueError(f"Question {question_id} not found")
        
        # Update fields
        if request.question_data is not None:
            # Validate question structure
            if not all(k in request.question_data for k in ["question_text", "options", "explanation"]):
                raise ValueError("question_data must contain: question_text, options, explanation")
            
            if len(request.question_data.get("options", [])) != 4:
                raise ValueError("question_data must have exactly 4 options")
            
            question.question_data = request.question_data
            
            # Recalculate content hash
            content_str = str(request.question_data)
            question.content_hash = hashlib.md5(content_str.encode()).hexdigest()
        
        if request.difficulty is not None:
            question.difficulty = request.difficulty
        
        if request.quality_score is not None:
            question.quality_score = request.quality_score
        
        if request.sub_topic is not None:
            question.sub_topic = request.sub_topic
        
        db.commit()
        db.refresh(question)
        
        # Update JSONL warehouse
        try:
            jsonl = JSONLBackup()
            updated_data = {
                'id': question.id,
                'language_id': question.language_id,
                'mapping_id': question.mapping_id,
                'sub_topic': question.sub_topic,
                'difficulty': question.difficulty,
                'question_data': question.question_data,
                'content_hash': question.content_hash,
                'is_verified': question.is_verified,
                'quality_score': question.quality_score,
                'created_at': question.created_at.isoformat() if question.created_at else None,
                'created_by': question.created_by
            }
            jsonl.update_question(question_id, updated_data)
            print(f"✅ Updated question {question_id[:8]} in JSONL warehouse")
        except Exception as e:
            print(f"⚠️ Failed to update JSONL warehouse: {e}")
        
        updated_question = AdminQuestion(
            id=question.id,
            language_id=question.language_id,
            mapping_id=question.mapping_id,
            sub_topic=question.sub_topic,
            difficulty=question.difficulty,
            question_data=question.question_data,
            content_hash=question.content_hash,
            is_verified=question.is_verified,
            quality_score=question.quality_score,
            times_used=question.times_used,
            times_correct=question.times_correct,
            calibrated_difficulty=question.calibrated_difficulty,
            created_at=question.created_at.isoformat() if question.created_at else "",
            created_by=question.created_by,
            review_notes=getattr(question, 'review_notes', None)
        )
        
        return AdminQuestionUpdateResponse(
            message="Question updated successfully",
            updated_question=updated_question
        )
    
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update question: {str(e)}")


@router.delete("/questions/{question_id}", response_model=AdminQuestionDeleteResponse)
async def delete_question(
    question_id: str,
    current_admin: dict = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
):
    """
    Delete a question permanently.
    
    **Use Case:** Admin removing low-quality or incorrect questions
    
    **Example:**
    DELETE /api/admin/questions/123e4567-e89b-12d3-a456-426614174000
    
    **Returns:**
    - Success confirmation
    - Deleted question ID
    
    **Requires:** Admin authentication
    
    **WARNING:** This action is irreversible
    """
    try:
        from services.content_engine.jsonl_backup import JSONLBackup
        
        question = db.query(QuestionBank).filter(QuestionBank.id == question_id).first()
        
        if not question:
            raise ValueError(f"Question {question_id} not found")
        
        # Delete associated history records (optional - can keep for analytics)
        # db.query(UserQuestionHistory).filter(UserQuestionHistory.question_id == question_id).delete()
        
        db.delete(question)
        db.commit()
        
        # Delete from JSONL warehouse
        try:
            jsonl = JSONLBackup()
            jsonl.delete_question(question_id)
            print(f"✅ Deleted question {question_id[:8]} from JSONL warehouse")
        except Exception as e:
            print(f"⚠️ Failed to delete from JSONL warehouse: {e}")
        
        return AdminQuestionDeleteResponse(
            message="Question deleted successfully",
            deleted_id=question_id
        )
    
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to delete question: {str(e)}")


@router.post("/questions/bulk-action", response_model=AdminBulkActionResponse)
async def bulk_action_questions(
    request: AdminBulkActionRequest,
    current_admin: dict = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
):
    """
    Perform bulk operations on multiple questions.
    
    **Actions:**
    - approve: Mark all as verified
    - delete: Delete all questions
    - update_difficulty: Update difficulty for all (requires params.difficulty)
    
    **Use Case:** Admin bulk approving pending questions or bulk deleting low-quality questions
    
    **Example:**
    POST /api/admin/questions/bulk-action
    Body: {
        "question_ids": ["id1", "id2", "id3"],
        "action": "approve"
    }
    
    **Returns:**
    - Success/failure counts
    - List of failed IDs
    
    **Requires:** Admin authentication
    """
    try:
        affected_count = 0
        failed_count = 0
        failed_ids = []
        
        for question_id in request.question_ids:
            try:
                question = db.query(QuestionBank).filter(QuestionBank.id == question_id).first()
                
                if not question:
                    failed_count += 1
                    failed_ids.append(question_id)
                    continue
                
                if request.action == "approve":
                    question.is_verified = True
                    affected_count += 1
                    
                    # Update JSONL warehouse
                    try:
                        from services.content_engine.jsonl_backup import JSONLBackup
                        jsonl = JSONLBackup()
                        updated_data = {
                            'id': question.id,
                            'language_id': question.language_id,
                            'mapping_id': question.mapping_id,
                            'sub_topic': question.sub_topic,
                            'difficulty': question.difficulty,
                            'question_data': question.question_data,
                            'content_hash': question.content_hash,
                            'is_verified': True,
                            'quality_score': question.quality_score,
                            'created_at': question.created_at.isoformat() if question.created_at else None,
                            'created_by': question.created_by
                        }
                        jsonl.update_question(question_id, updated_data)
                    except Exception as e:
                        print(f"⚠️ Failed to update {question_id[:8]} in JSONL: {e}")
                
                elif request.action == "delete":
                    db.delete(question)
                    affected_count += 1
                    
                    # Delete from JSONL warehouse
                    try:
                        from services.content_engine.jsonl_backup import JSONLBackup
                        jsonl = JSONLBackup()
                        jsonl.delete_question(question_id)
                    except Exception as e:
                        print(f"⚠️ Failed to delete {question_id[:8]} from JSONL: {e}")
                
                elif request.action == "update_difficulty":
                    if not request.params or "difficulty" not in request.params:
                        raise ValueError("update_difficulty requires params.difficulty")
                    question.difficulty = request.params["difficulty"]
                    affected_count += 1
                
                else:
                    raise ValueError(f"Invalid action: {request.action}")
            
            except Exception as e:
                failed_count += 1
                failed_ids.append(question_id)
                print(f"Failed to process {question_id}: {e}")
        
        db.commit()
        
        action_messages = {
            "approve": f"Approved {affected_count} questions",
            "delete": f"Deleted {affected_count} questions",
            "update_difficulty": f"Updated difficulty for {affected_count} questions"
        }
        
        return AdminBulkActionResponse(
            message=action_messages.get(request.action, f"Processed {affected_count} questions"),
            affected_count=affected_count,
            failed_count=failed_count,
            failed_ids=failed_ids
        )
    
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Bulk action failed: {str(e)}")


@router.get("/questions/{question_id}/analytics", response_model=AdminQuestionAnalytics)
async def get_question_analytics(
    question_id: str,
    current_admin: dict = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
):
    """
    Get performance analytics for a specific question.
    
    **Use Case:** Admin reviewing question quality and difficulty calibration
    
    **Example:**
    GET /api/admin/questions/123e4567-e89b-12d3-a456-426614174000/analytics
    
    **Returns:**
    - Usage count, accuracy rate
    - Average time spent
    - Quality metrics
    - Calibrated vs assigned difficulty
    
    **Requires:** Admin authentication
    """
    try:
        question = db.query(QuestionBank).filter(QuestionBank.id == question_id).first()
        
        if not question:
            raise ValueError(f"Question {question_id} not found")
        
        # Calculate accuracy rate
        accuracy_rate = 0.0
        if question.times_used > 0:
            accuracy_rate = (question.times_correct / question.times_used) * 100
        
        # Get average time spent from history
        avg_time_result = db.query(func.avg(UserQuestionHistory.time_spent_seconds)).filter(
            UserQuestionHistory.question_id == question_id
        ).scalar()
        
        avg_time_spent = float(avg_time_result) if avg_time_result else None
        
        return AdminQuestionAnalytics(
            question_id=question.id,
            times_used=question.times_used,
            times_correct=question.times_correct,
            accuracy_rate=round(accuracy_rate, 2),
            avg_time_spent=round(avg_time_spent, 2) if avg_time_spent else None,
            quality_score=question.quality_score,
            calibrated_difficulty=question.calibrated_difficulty,
            assigned_difficulty=question.difficulty
        )
    
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to retrieve analytics: {str(e)}")


@router.get("/metrics/high-failure-questions", response_model=AdminHighFailureQuestionsResponse)
async def get_high_failure_questions(
    language_id: Optional[str] = Query(None, description="Filter by language_id"),
    window_days: int = Query(30, description="Window size in days (1-3650)."),
    limit: int = Query(10, ge=1, le=50, description="Maximum questions to return"),
    current_admin: dict = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
):
    """Get questions with the highest failure rates within a time window."""
    try:
        validated_window_days = _validate_window_days(window_days)
        cutoff = datetime.now(timezone.utc) - timedelta(days=validated_window_days)

        sessions_query = text("""
            SELECT
                es.language_id,
                ed.questions_snapshot
            FROM exam_details ed
            INNER JOIN exam_sessions es ON es.id = ed.session_id
            WHERE es.session_status = 'completed'
              AND COALESCE(es.completed_at, es.created_at) >= :cutoff
              AND (:language_id IS NULL OR es.language_id = :language_id)
        """)

        session_rows = db.execute(sessions_query, {
            "cutoff": cutoff,
            "language_id": language_id,
        }).mappings().all()

        aggregates: Dict[str, dict] = {}
        for row in session_rows:
            snapshot = row.get("questions_snapshot")
            if isinstance(snapshot, str):
                try:
                    snapshot = json.loads(snapshot)
                except Exception:
                    continue

            if not isinstance(snapshot, dict):
                continue

            questions_payload = snapshot.get("questions", [])
            if not isinstance(questions_payload, list):
                continue

            session_language = str(row.get("language_id") or "")

            for item in questions_payload:
                if not isinstance(item, dict):
                    continue

                question_id = str(item.get("q_id") or "").strip()
                if not question_id:
                    continue

                bucket = aggregates.setdefault(question_id, {
                    "question_id": question_id,
                    "language_id": session_language,
                    "mapping_id": str(item.get("sub_topic") or ""),
                    "sub_topic": item.get("sub_topic"),
                    "question_text": str(item.get("question_text") or ""),
                    "total_attempts": 0,
                    "total_correct": 0,
                    "time_sum": 0.0,
                    "time_count": 0,
                })

                bucket["total_attempts"] += 1
                if item.get("is_correct") is True:
                    bucket["total_correct"] += 1

                time_spent = item.get("time_spent")
                if isinstance(time_spent, (int, float)):
                    bucket["time_sum"] += float(time_spent)
                    bucket["time_count"] += 1

        if not aggregates:
            return AdminHighFailureQuestionsResponse(
                language_id=language_id,
                window_days=validated_window_days,
                limit=limit,
                questions=[],
            )

        question_ids = list(aggregates.keys())
        placeholders = ", ".join([f":q{i}" for i in range(len(question_ids))])
        question_params = {f"q{i}": question_id for i, question_id in enumerate(question_ids)}

        metadata_query = text(f"""
            SELECT id, language_id, mapping_id, sub_topic, question_data
            FROM question_bank
            WHERE id IN ({placeholders})
        """)
        metadata_rows = db.execute(metadata_query, question_params).mappings().all()
        metadata_map = {str(row["id"]): row for row in metadata_rows}

        report_count_map: Dict[str, int] = {}
        try:
            report_query = text(f"""
                SELECT qr.question_id, COUNT(*) AS report_count
                FROM question_reports qr
                INNER JOIN question_bank qb ON qb.id = qr.question_id
                WHERE qr.created_at >= :cutoff
                  AND qr.question_id IN ({placeholders})
                  AND (:language_id IS NULL OR qb.language_id = :language_id)
                GROUP BY qr.question_id
            """)

            report_params = {
                "cutoff": cutoff,
                "language_id": language_id,
                **question_params,
            }
            report_rows = db.execute(report_query, report_params).mappings().all()
            report_count_map = {
                str(row["question_id"]): int(row["report_count"] or 0)
                for row in report_rows
            }
        except Exception:
            report_count_map = {}

        questions = []
        for question_id, aggregate in aggregates.items():
            total_attempts = int(aggregate["total_attempts"] or 0)
            total_correct = int(aggregate["total_correct"] or 0)
            failure_rate = 0.0
            if total_attempts > 0:
                failure_rate = ((total_attempts - total_correct) / total_attempts) * 100

            metadata = metadata_map.get(question_id, {})
            mapping_id = str(
                metadata.get("mapping_id")
                or aggregate.get("mapping_id")
                or metadata.get("sub_topic")
                or ""
            )
            question_text = _extract_question_text(metadata.get("question_data")) or str(aggregate.get("question_text") or "")
            avg_time_seconds = None
            if int(aggregate["time_count"] or 0) > 0:
                avg_time_seconds = aggregate["time_sum"] / aggregate["time_count"]

            questions.append(AdminHighFailureQuestion(
                question_id=question_id,
                language_id=str(metadata.get("language_id") or aggregate.get("language_id") or "unknown"),
                concept=_get_concept_name(mapping_id),
                sub_topic=metadata.get("sub_topic") or aggregate.get("sub_topic"),
                question_text=question_text,
                failure_rate=round(float(failure_rate), 2),
                total_attempts=total_attempts,
                report_count=report_count_map.get(question_id, 0),
                avg_time_seconds=round(float(avg_time_seconds), 2) if avg_time_seconds is not None else None,
            ))

        questions.sort(key=lambda question: (question.failure_rate, question.total_attempts), reverse=True)

        return AdminHighFailureQuestionsResponse(
            language_id=language_id,
            window_days=validated_window_days,
            limit=limit,
            questions=questions[:limit],
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to retrieve high-failure questions: {str(e)}")


@router.get("/metrics/most-reported-questions", response_model=AdminMostReportedQuestionsResponse)
async def get_most_reported_questions(
    language_id: Optional[str] = Query(None, description="Filter by language_id"),
    window_days: int = Query(30, description="Window size in days (1-3650)."),
    limit: int = Query(10, ge=1, le=50, description="Maximum questions to return"),
    current_admin: dict = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
):
    """Get questions with the highest report volume within a time window."""
    try:
        validated_window_days = _validate_window_days(window_days)
        cutoff = datetime.now(timezone.utc) - timedelta(days=validated_window_days)

        issue_column = _get_question_reports_issue_column(db)

        if issue_column == "report_type":
            query = text("""
                SELECT
                    qr.question_id,
                    qr.report_type AS issue_type,
                    COUNT(*) AS report_count,
                    MAX(qr.created_at) AS last_reported,
                    qb.language_id,
                    qb.mapping_id,
                    qb.question_data,
                    qb.times_used,
                    qb.times_correct
                FROM question_reports qr
                INNER JOIN question_bank qb ON qb.id = qr.question_id
                WHERE qr.created_at >= :cutoff
                  AND (:language_id IS NULL OR qb.language_id = :language_id)
                GROUP BY
                    qr.question_id,
                    qr.report_type,
                    qb.language_id,
                    qb.mapping_id,
                    qb.question_data,
                    qb.times_used,
                    qb.times_correct
                ORDER BY COUNT(*) DESC
            """)
        elif issue_column == "report_reason":
            query = text("""
                SELECT
                    qr.question_id,
                    qr.report_reason AS issue_type,
                    COUNT(*) AS report_count,
                    MAX(qr.created_at) AS last_reported,
                    qb.language_id,
                    qb.mapping_id,
                    qb.question_data,
                    qb.times_used,
                    qb.times_correct
                FROM question_reports qr
                INNER JOIN question_bank qb ON qb.id = qr.question_id
                WHERE qr.created_at >= :cutoff
                  AND (:language_id IS NULL OR qb.language_id = :language_id)
                GROUP BY
                    qr.question_id,
                    qr.report_reason,
                    qb.language_id,
                    qb.mapping_id,
                    qb.question_data,
                    qb.times_used,
                    qb.times_correct
                ORDER BY COUNT(*) DESC
            """)
        else:
            query = text("""
                SELECT
                    qr.question_id,
                    'other' AS issue_type,
                    COUNT(*) AS report_count,
                    MAX(qr.created_at) AS last_reported,
                    qb.language_id,
                    qb.mapping_id,
                    qb.question_data,
                    qb.times_used,
                    qb.times_correct
                FROM question_reports qr
                INNER JOIN question_bank qb ON qb.id = qr.question_id
                WHERE qr.created_at >= :cutoff
                  AND (:language_id IS NULL OR qb.language_id = :language_id)
                GROUP BY
                    qr.question_id,
                    qb.language_id,
                    qb.mapping_id,
                    qb.question_data,
                    qb.times_used,
                    qb.times_correct
                ORDER BY COUNT(*) DESC
            """)

        rows = db.execute(query, {
            "cutoff": cutoff,
            "language_id": language_id,
        }).mappings().all()

        grouped: Dict[str, dict] = {}
        for row in rows:
            question_id = str(row["question_id"])
            if question_id not in grouped:
                grouped[question_id] = {
                    "question_id": question_id,
                    "language_id": str(row["language_id"]),
                    "mapping_id": str(row["mapping_id"] or ""),
                    "question_data": row["question_data"],
                    "report_count": 0,
                    "issue_counts": defaultdict(int),
                    "last_reported": row["last_reported"],
                    "times_used": int(row["times_used"] or 0),
                    "times_correct": int(row["times_correct"] or 0),
                }

            grouped_item = grouped[question_id]
            issue_count = int(row["report_count"] or 0)
            grouped_item["report_count"] += issue_count
            grouped_item["issue_counts"][str(row["issue_type"] or "other")] += issue_count

            last_reported = row["last_reported"]
            if last_reported and (grouped_item["last_reported"] is None or last_reported > grouped_item["last_reported"]):
                grouped_item["last_reported"] = last_reported

        sorted_items = sorted(grouped.values(), key=lambda item: item["report_count"], reverse=True)[:limit]

        questions = []
        for item in sorted_items:
            times_used = item["times_used"]
            times_correct = item["times_correct"]
            failure_rate = 0.0
            if times_used > 0:
                failure_rate = ((times_used - times_correct) / times_used) * 100

            main_issue = "other"
            if item["issue_counts"]:
                main_issue = max(item["issue_counts"].items(), key=lambda issue: issue[1])[0]

            last_reported = item["last_reported"]
            questions.append(AdminMostReportedQuestion(
                question_id=item["question_id"],
                language_id=item["language_id"],
                concept=_get_concept_name(item["mapping_id"]),
                question_text=_extract_question_text(item["question_data"]),
                report_count=item["report_count"],
                failure_rate=round(float(failure_rate), 2),
                last_reported=(
                    last_reported.isoformat()
                    if isinstance(last_reported, datetime)
                    else str(last_reported) if isinstance(last_reported, str) else None
                ),
                main_issue=main_issue,
            ))

        return AdminMostReportedQuestionsResponse(
            language_id=language_id,
            window_days=validated_window_days,
            limit=limit,
            questions=questions,
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to retrieve most-reported questions: {str(e)}")


@router.get("/metrics/concept-time-stats", response_model=AdminConceptTimeStatsResponse)
async def get_concept_time_stats(
    language_id: Optional[str] = Query(None, description="Filter by language_id"),
    window_days: int = Query(30, description="Window size in days (1-3650)."),
    limit: int = Query(10, ge=1, le=50, description="Maximum concepts to return"),
    current_admin: dict = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
):
    """Get average completion time by concept within a time window."""
    try:
        validated_window_days = _validate_window_days(window_days)
        cutoff = datetime.now(timezone.utc) - timedelta(days=validated_window_days)

        query = text("""
            SELECT
                s.language_id,
                s.major_topic_id,
                COUNT(*) AS session_count,
                COALESCE(AVG(COALESCE(s.time_taken_seconds, 0)), 0) AS avg_time_seconds,
                COALESCE(AVG(COALESCE(s.difficulty_assigned, 0.5)), 0.5) AS avg_difficulty
            FROM exam_sessions s
            WHERE s.session_status = 'completed'
              AND COALESCE(s.completed_at, s.created_at) >= :cutoff
              AND (:language_id IS NULL OR s.language_id = :language_id)
            GROUP BY s.language_id, s.major_topic_id
        """)

        rows = db.execute(query, {
            "cutoff": cutoff,
            "language_id": language_id,
        }).mappings().all()

        aggregated: Dict[str, dict] = {}
        for row in rows:
            row_language = str(row["language_id"])
            major_topic_id = str(row["major_topic_id"])
            mapping_id = _resolve_mapping_id(row_language, major_topic_id)
            session_count = int(row["session_count"] or 0)
            avg_time_seconds = float(row["avg_time_seconds"] or 0)
            avg_difficulty = float(row["avg_difficulty"] or 0.5)

            if mapping_id not in aggregated:
                aggregated[mapping_id] = {
                    "mapping_id": mapping_id,
                    "concept": _get_concept_name(mapping_id),
                    "session_count": 0,
                    "weighted_time": 0.0,
                    "weighted_difficulty": 0.0,
                }

            bucket = aggregated[mapping_id]
            bucket["session_count"] += session_count
            bucket["weighted_time"] += avg_time_seconds * session_count
            bucket["weighted_difficulty"] += avg_difficulty * session_count

        concepts: List[AdminConceptTimeStat] = []
        for bucket in aggregated.values():
            session_count = bucket["session_count"]
            if session_count <= 0:
                continue

            concepts.append(AdminConceptTimeStat(
                concept=bucket["concept"],
                mapping_id=bucket["mapping_id"],
                avg_time_seconds=round(bucket["weighted_time"] / session_count, 2),
                avg_difficulty=round(bucket["weighted_difficulty"] / session_count, 3),
                session_count=session_count,
            ))

        concepts.sort(key=lambda concept: concept.avg_time_seconds, reverse=True)

        return AdminConceptTimeStatsResponse(
            language_id=language_id,
            window_days=validated_window_days,
            limit=limit,
            concepts=concepts[:limit],
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to retrieve concept-time stats: {str(e)}")


@router.get("/metrics/error-pattern-trends", response_model=AdminErrorPatternTrendsResponse)
async def get_error_pattern_trends(
    language_id: Optional[str] = Query(None, description="Filter by language_id"),
    window_days: int = Query(30, description="Window size in days (1-3650)."),
    limit: int = Query(10, ge=1, le=50, description="Maximum error patterns to return"),
    current_admin: dict = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
):
    """Get most frequent error patterns, percentages, and short-term trend direction."""
    try:
        validated_window_days = _validate_window_days(window_days)
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=validated_window_days)
        trend_current_cutoff = now - timedelta(days=7)
        trend_previous_cutoff = now - timedelta(days=14)

        counts_query = text("""
            SELECT
                eh.error_type,
                COUNT(*) AS error_count
            FROM error_history eh
            WHERE eh.occurred_at >= :cutoff
              AND (:language_id IS NULL OR eh.language_id = :language_id)
            GROUP BY eh.error_type
            ORDER BY COUNT(*) DESC
        """)
        counts_rows = db.execute(counts_query, {
            "cutoff": cutoff,
            "language_id": language_id,
        }).mappings().all()

        trend_query = text("""
            SELECT
                eh.error_type,
                SUM(CASE WHEN eh.occurred_at >= :trend_current_cutoff THEN 1 ELSE 0 END) AS current_count,
                SUM(CASE WHEN eh.occurred_at >= :trend_previous_cutoff AND eh.occurred_at < :trend_current_cutoff THEN 1 ELSE 0 END) AS previous_count
            FROM error_history eh
            WHERE eh.occurred_at >= :trend_previous_cutoff
              AND (:language_id IS NULL OR eh.language_id = :language_id)
            GROUP BY eh.error_type
        """)
        trend_rows = db.execute(trend_query, {
            "trend_current_cutoff": trend_current_cutoff,
            "trend_previous_cutoff": trend_previous_cutoff,
            "language_id": language_id,
        }).mappings().all()
        trend_map = {
            str(row["error_type"]): {
                "current": int(row["current_count"] or 0),
                "previous": int(row["previous_count"] or 0),
            }
            for row in trend_rows
        }

        concept_query = text("""
            SELECT
                eh.error_type,
                eh.mapping_id,
                COUNT(*) AS concept_count
            FROM error_history eh
            WHERE eh.occurred_at >= :cutoff
              AND (:language_id IS NULL OR eh.language_id = :language_id)
            GROUP BY eh.error_type, eh.mapping_id
            ORDER BY eh.error_type, COUNT(*) DESC
        """)
        concept_rows = db.execute(concept_query, {
            "cutoff": cutoff,
            "language_id": language_id,
        }).mappings().all()

        top_concepts_map: Dict[str, List[str]] = defaultdict(list)
        for row in concept_rows:
            error_type = str(row["error_type"])
            mapping_id = str(row["mapping_id"] or "")
            concept_name = _get_concept_name(mapping_id)

            existing = top_concepts_map[error_type]
            if concept_name and concept_name not in existing and len(existing) < 3:
                existing.append(concept_name)

        total_errors = sum(int(row["error_count"] or 0) for row in counts_rows)
        patterns: List[AdminErrorPatternTrend] = []

        for row in counts_rows[:limit]:
            error_type = str(row["error_type"])
            count = int(row["error_count"] or 0)
            percentage = (count * 100.0 / total_errors) if total_errors > 0 else 0.0

            trend_values = trend_map.get(error_type, {"current": 0, "previous": 0})
            current_count = trend_values["current"]
            previous_count = trend_values["previous"]
            if current_count > previous_count:
                trend = "up"
            elif current_count < previous_count:
                trend = "down"
            else:
                trend = "stable"

            patterns.append(AdminErrorPatternTrend(
                error_type=error_type,
                count=count,
                percentage=round(percentage, 2),
                top_concepts=top_concepts_map.get(error_type, []),
                trend=trend,
            ))

        return AdminErrorPatternTrendsResponse(
            language_id=language_id,
            window_days=validated_window_days,
            limit=limit,
            total_errors=total_errors,
            patterns=patterns,
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to retrieve error-pattern trends: {str(e)}")


@router.get("/users/analytics", response_model=AdminUserAnalytics)
async def get_user_analytics(
    current_admin: dict = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
):
    """
    Get comprehensive user analytics for admin dashboard.
    
    **Use Case:** Admin dashboard statistics cards and charts
    
    **Example:**
    GET /api/admin/users/analytics
    
    **Returns:**
    - User counts by status
    - New user growth metrics
    - Platform-wide engagement statistics
    - Language usage distribution
    
    **Requires:** Admin authentication
    """
    try:
        user_service = UserService(db)
        analytics_data = user_service.get_user_analytics_admin()
        
        return AdminUserAnalytics(**analytics_data)
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to retrieve analytics: {str(e)}")


@router.patch("/users/{user_id}", response_model=AdminUserUpdateResponse)
async def update_user_details(
    user_id: str,
    request: AdminUserUpdateRequest,
    current_admin: dict = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
):
    """
    Update user details (name, language, etc.).
    
    **Use Case:** Admin editing user profile information
    
    **Example:**
    PATCH /api/admin/users/123e4567-e89b-12d3-a456-426614174000
    Body: {"name": "New Name", "language": "python_3"}
    
    **Returns:**
    - Success confirmation
    - Updated user data
    
    **Requires:** Admin authentication
    """
    try:
        user_service = UserService(db)
        updated_user = user_service.update_user_details_admin(user_id, request)
        
        return AdminUserUpdateResponse(
            message="User details updated successfully",
            updated_user=updated_user
        )
    
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update user details: {str(e)}")


@router.post("/users/{user_id}/reset-password", response_model=AdminPasswordResetResponse)
async def reset_user_password(
    user_id: str,
    request: AdminPasswordResetRequest,
    current_admin: dict = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
):
    """
    Reset a user's password (admin only).
    
    **Use Case:** Admin helping users who forgot passwords or need password resets
    
    **Example:**
    POST /api/admin/users/123e4567-e89b-12d3-a456-426614174000/reset-password
    Body: {"new_password": "newSecurePassword123"}
    
    **Returns:**
    - Success confirmation
    
    **Requires:** Admin authentication
    """
    try:
        user_service = UserService(db)
        user_service.reset_user_password_admin(user_id, request.new_password)
        
        return AdminPasswordResetResponse(
            message="User password has been reset successfully"
        )
    
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to reset user password: {str(e)}")


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: str,
    current_admin: dict = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
):
    """
    Delete a user account permanently.
    
    **Use Case:** Admin removing spam accounts or handling data deletion requests
    
    **Example:**
    DELETE /api/admin/users/123e4567-e89b-12d3-a456-426614174000
    
    **Returns:**
    - Success confirmation
    
    **Requires:** Admin authentication
    
    **WARNING:** This action is irreversible and will delete all user data
    """
    try:
        user_service = UserService(db)
        user_service.delete_user_admin(user_id)
        
        return {"success": True, "message": "User account has been permanently deleted"}
    
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete user: {str(e)}")