"""
Question Bank API Endpoints
Provides REST API for question generation, selection, and admin review.
"""
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, status, Request
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from typing import List, Optional, Dict
from datetime import datetime
import uuid

from database import get_db
from models.question_bank import QuestionBank, UserQuestionHistory
from services.content_engine.openai_factory import OpenAIFactory
from services.content_engine.selector import QuestionSelector
from services.content_engine.validator import MultiLanguageValidator
from services.auth import get_current_active_user, get_current_admin_user
from slowapi import Limiter
from slowapi.util import get_remote_address


router = APIRouter(prefix="/question-bank", tags=["Question Bank"])
limiter = Limiter(key_func=get_remote_address)


# ==================== REQUEST/RESPONSE SCHEMAS ====================

class GenerateRequest(BaseModel):
    """Request to generate questions."""
    topic: str = Field(..., description="Topic name (e.g., 'for loops')")
    language_id: str = Field(..., description="Language: python_3, javascript_es6, etc.")
    mapping_id: str = Field(..., description="Curriculum node: UNIV_LOOP, UNIV_VAR, etc.")
    difficulty: float = Field(..., ge=0.0, le=1.0, description="Difficulty: 0.0 (easy) to 1.0 (hard)")
    count: int = Field(default=10, ge=1, le=50, description="Number of questions to generate")
    sub_topic: Optional[str] = Field(None, description="Optional sub-topic refinement")


class GenerateResponse(BaseModel):
    """Response from generate endpoint."""
    task_id: str
    message: str
    estimated_time_seconds: int


class SelectRequest(BaseModel):
    """Request to select questions for exam."""
    user_id: str = Field(..., description="Student UUID")
    language_id: str
    mapping_id: str
    target_difficulty: float = Field(..., ge=0.0, le=1.0)
    count: int = Field(default=10, ge=1, le=50)
    difficulty_tolerance: float = Field(default=0.1, ge=0.0, le=0.5)


class QuestionResponse(BaseModel):
    """Single question response."""
    id: str
    question_data: Dict
    difficulty: float
    quality_score: float
    is_verified: bool

    class Config:
        from_attributes = True


class SelectResponse(BaseModel):
    """Response from select endpoint."""
    questions: List[QuestionResponse]
    total_selected: int
    warehouse_status: Dict


class MarkSeenRequest(BaseModel):
    """Request to mark questions as seen."""
    user_id: str
    question_ids: List[str]
    session_id: Optional[str] = None
    results: Optional[List[Dict]] = Field(
        None, 
        description="Optional performance data: [{question_id, was_correct, time_spent_seconds}]"
    )


class MarkSeenResponse(BaseModel):
    """Response from mark-seen endpoint."""
    marked_count: int
    message: str


class WarehouseStatusResponse(BaseModel):
    """Warehouse status response."""
    language_id: str
    mapping_id: str
    difficulty: float
    total: int
    verified: int
    unverified: int
    status: str
    avg_quality_score: float


class AdminReviewRequest(BaseModel):
    """Request to approve/reject question."""
    question_id: str
    action: str = Field(..., description="'approve' or 'reject'")
    reviewer_notes: Optional[str] = None


class AdminReviewResponse(BaseModel):
    """Response from admin review."""
    question_id: str
    action: str
    message: str


class QuestionReportRequest(BaseModel):
    """Request to report a problematic question."""
    question_id: str = Field(..., description="ID of the question being reported")
    report_reason: str = Field(..., description="Category: incorrect_answer, typo, unclear, outdated, offensive")
    description: Optional[str] = Field(None, max_length=500, description="Detailed description of the issue")


class QuestionReportResponse(BaseModel):
    """Response from question report."""
    report_id: str
    message: str
    status: str = "pending"


class QuestionAnalyticsResponse(BaseModel):
    """Analytics for a specific question."""
    question_id: str
    usage_count: int
    total_attempts: int
    correct_attempts: int
    accuracy_rate: float
    avg_time_spent: float
    difficulty_rating: float
    quality_score: float
    is_verified: bool
    created_at: str
    last_used_at: Optional[str] = None


class QuestionAnalyticsSummaryResponse(BaseModel):
    """Summary analytics across all questions."""
    total_questions: int
    verified_count: int
    unverified_count: int
    total_usage: int
    avg_accuracy_rate: float
    questions_needing_review: int
    low_quality_questions: List[str] = Field(description="Question IDs with quality  < 0.5")


# ==================== BACKGROUND TASKS ====================

def _background_generate(
    topic: str,
    language_id: str,
    mapping_id: str,
    difficulty: float,
    count: int,
    sub_topic: Optional[str],
    task_id: str
):
    """
    Background task for question generation.
    This runs asynchronously so API returns immediately.
    Saves to both database AND JSONL backup for durability.
    """
    from database import get_db_context
    from services.content_engine.jsonl_backup import JSONLBackup
    
    print(f"[Background Task {task_id[:8]}] Starting generation of {count} questions...")
    
    try:
        factory = OpenAIFactory()
        validator = MultiLanguageValidator()
        jsonl = JSONLBackup()  # Initialize JSONL backup
        
        generated = []
        backup_questions = []  # Collect for batch JSONL backup
        
        for i in range(count):
            try:
                # Generate question
                question_data = factory.generate_question(
                    topic=topic,
                    language_id=language_id,
                    mapping_id=mapping_id,
                    difficulty=difficulty,
                    sub_topic=sub_topic
                )
                
                # Calculate content hash for deduplication
                content_hash = validator.generate_content_hash(question_data)
                
                # Create database record
                with get_db_context() as db:
                    # Check for duplicate
                    existing = db.query(QuestionBank).filter(
                        QuestionBank.content_hash == content_hash
                    ).first()
                    
                    if existing:
                        print(f"[Task {task_id[:8]}] Skipped duplicate question {i+1}/{count}")
                        continue
                    
                    question_id = str(uuid.uuid4())
                    question = QuestionBank(
                        id=question_id,
                        language_id=language_id,
                        mapping_id=mapping_id,
                        sub_topic=sub_topic or question_data.get('sub_topic'),
                        difficulty=difficulty,
                        question_data=question_data,
                        content_hash=content_hash,
                        is_verified=False,  # Requires admin review
                        quality_score=question_data.get('quality_score', 0.5)
                    )
                    
                    db.add(question)
                    db.commit()
                    
                    generated.append(question_id)
                    
                    # Prepare for JSONL backup
                    backup_data = {
                        'id': question_id,
                        'language_id': language_id,
                        'mapping_id': mapping_id,
                        'sub_topic': sub_topic,
                        'difficulty': difficulty,
                        'content_hash': content_hash,
                        'question_data': question_data,
                        'created_at': question.created_at.isoformat() if question.created_at else None,
                        'is_verified': False,
                        'quality_score': question_data.get('quality_score', 0.5)
                    }
                    backup_questions.append(backup_data)
                    
                    print(f"[Task {task_id[:8]}] Generated question {i+1}/{count}: {question_id[:8]}")
            
            except Exception as e:
                print(f"[Task {task_id[:8]}] Error generating question {i+1}: {e}")
                continue
        
        # Backup to JSONL (batch operation for performance)
        if backup_questions:
            try:
                backed_up = jsonl.append_batch(backup_questions)
                print(f"[Task {task_id[:8]}] ✅ Backed up {backed_up} questions to JSONL")
            except Exception as e:
                print(f"[Task {task_id[:8]}] ⚠️ JSONL backup failed (data safe in DB): {e}")
        
        print(f"[Background Task {task_id[:8]}] Completed! Generated {len(generated)}/{count} questions")
    
    except Exception as e:
        print(f"[Background Task {task_id[:8]}] FAILED: {e}")
        import traceback
        traceback.print_exc()


# ==================== API ENDPOINTS ====================

@router.post("/generate", response_model=GenerateResponse, status_code=status.HTTP_202_ACCEPTED)
@limiter.limit("50/minute")
async def generate_questions(
    req: Request,
    payload: GenerateRequest,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Generate MCQ questions using OpenAI GPT-4o-mini (async background task).
    
    Returns immediately with task_id.
    Questions are generated in background and stored as 'unverified'.
    Admin must review and approve before they're used in exams.
    
    Rate Limiting: 50 requests/minute per IP
    """
    # Validate inputs
    if payload.language_id not in ["python_3", "javascript_es6", "java_17", "cpp_20", "go_1_21"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported language: {payload.language_id}"
        )
    
    # Generate task ID
    task_id = str(uuid.uuid4())
    
    # Schedule background generation
    background_tasks.add_task(
        _background_generate,
        topic=payload.topic,
        language_id=payload.language_id,
        mapping_id=payload.mapping_id,
        difficulty=payload.difficulty,
        count=payload.count,
        sub_topic=payload.sub_topic,
        task_id=task_id
    )
    
    # Estimate time (1-2 seconds per question with OpenAI API)
    estimated_time = payload.count * 1.5
    
    return GenerateResponse(
        task_id=task_id,
        message=f"Generation started. Creating {payload.count} questions for '{payload.topic}'.",
        estimated_time_seconds=int(estimated_time)
    )


@router.post("/select", response_model=SelectResponse)
async def select_questions(
    payload: SelectRequest,
    current_user: dict = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Select questions for an exam (excludes already-seen questions).
    
    Uses 3-strategy waterfall:
    1. Verified unseen questions (best)
    2. Unverified unseen questions (acceptable)
    3. Verified seen questions (fallback when warehouse low)
    
    Returns fewer than requested if warehouse is empty.
    """
    selector = QuestionSelector(db)
    
    # Select questions
    questions = selector.select_questions(
        user_id=payload.user_id,
        language_id=payload.language_id,
        mapping_id=payload.mapping_id,
        target_difficulty=payload.target_difficulty,
        count=payload.count,
        difficulty_tolerance=payload.difficulty_tolerance
    )
    
    # Get warehouse status for this topic
    warehouse_status = selector.get_warehouse_status(
        language_id=payload.language_id,
        mapping_id=payload.mapping_id,
        difficulty=payload.target_difficulty,
        difficulty_tolerance=payload.difficulty_tolerance
    )
    
    return SelectResponse(
        questions=[QuestionResponse.from_orm(q) for q in questions],
        total_selected=len(questions),
        warehouse_status=warehouse_status
    )


@router.post("/mark-seen", response_model=MarkSeenResponse)
async def mark_questions_seen(
    request: MarkSeenRequest,
    db: Session = Depends(get_db)
):
    """
    Mark questions as seen by user (prevents future repetition).
    
    Optionally include performance data (was_correct, time_spent_seconds)
    for analytics and difficulty calibration.
    """
    selector = QuestionSelector(db)
    
    # Validate question IDs exist
    existing_count = db.query(QuestionBank).filter(
        QuestionBank.id.in_(request.question_ids)
    ).count()
    
    if existing_count != len(request.question_ids):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Some question IDs not found. Expected {len(request.question_ids)}, found {existing_count}"
        )
    
    # Mark as seen
    selector.mark_questions_seen(
        user_id=request.user_id,
        question_ids=request.question_ids,
        session_id=request.session_id,
        results=request.results
    )
    
    return MarkSeenResponse(
        marked_count=len(request.question_ids),
        message=f"Marked {len(request.question_ids)} questions as seen for user {request.user_id[:8]}"
    )


@router.get("/warehouse-status", response_model=WarehouseStatusResponse)
async def get_warehouse_status(
    language_id: str,
    mapping_id: str,
    difficulty: float,
    difficulty_tolerance: float = 0.1,
    db: Session = Depends(get_db)
):
    """
    Check question stock levels for a topic/difficulty.
    
    Returns:
    - total: Total questions available
    - verified: Questions approved by admin
    - unverified: Questions pending review
    - status: 'healthy' (50+), 'low' (20-49), 'critical' (<20)
    - avg_quality_score: Average AI-assessed quality
    
    Use this to trigger background replenishment.
    """
    selector = QuestionSelector(db)
    
    status_data = selector.get_warehouse_status(
        language_id=language_id,
        mapping_id=mapping_id,
        difficulty=difficulty,
        difficulty_tolerance=difficulty_tolerance
    )
    
    return WarehouseStatusResponse(
        language_id=language_id,
        mapping_id=mapping_id,
        difficulty=difficulty,
        **status_data
    )


@router.post("/admin/review", response_model=AdminReviewResponse)
async def admin_review_question(
    payload: AdminReviewRequest,
    current_user: dict = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
):
    """
    Admin endpoint to approve or reject generated questions.
    
    Actions:
    - 'approve': Mark as verified (can be used in exams)
    - 'reject': Delete from database
    
    Requires admin authentication.
    """
    # Get question
    question = db.query(QuestionBank).filter(
        QuestionBank.id == payload.question_id
    ).first()
    
    if not question:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Question {payload.question_id} not found"
        )
    
    if payload.action == "approve":
        question.is_verified = True
        question.review_notes = payload.reviewer_notes
        db.commit()
        
        return AdminReviewResponse(
            question_id=payload.question_id,
            action="approve",
            message=f"Question {payload.question_id[:8]} approved and verified"
        )
    
    elif payload.action == "reject":
        db.delete(question)
        db.commit()
        
        return AdminReviewResponse(
            question_id=payload.question_id,
            action="reject",
            message=f"Question {payload.question_id[:8]} rejected and deleted"
        )
    
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid action: {payload.action}. Use 'approve' or 'reject'"
        )


@router.get("/admin/pending")
async def get_pending_questions(
    language_id: Optional[str] = None,
    mapping_id: Optional[str] = None,
    limit: int = 50,
    db: Session = Depends(get_db)
):
    """
    Get unverified questions pending admin review.
    
    Optional filters:
    - language_id: Filter by programming language
    - mapping_id: Filter by curriculum topic
    - limit: Max questions to return (default 50)
    
    Requires admin authentication (TODO: Add auth middleware)
    """
    query = db.query(QuestionBank).filter(
        QuestionBank.is_verified == False
    )
    
    if language_id:
        query = query.filter(QuestionBank.language_id == language_id)
    
    if mapping_id:
        query = query.filter(QuestionBank.mapping_id == mapping_id)
    
    questions = query.order_by(
        QuestionBank.created_at.desc()
    ).limit(limit).all()
    
    return {
        "total_pending": len(questions),
        "questions": [
            {
                "id": q.id,
                "language_id": q.language_id,
                "mapping_id": q.mapping_id,
                "difficulty": q.difficulty,
                "quality_score": q.quality_score,
                "question_data": q.question_data,
                "created_at": q.created_at.isoformat() if q.created_at else None
            }
            for q in questions
        ]
    }


@router.post("/report", response_model=QuestionReportResponse)
async def report_question(
    payload: QuestionReportRequest,
    current_user: dict = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Report a problematic question.
    
    Users can report questions for:
    - incorrect_answer: Answer key is wrong
    - typo: Spelling or grammar errors
    - unclear: Question is confusing or ambiguous
    - outdated: Uses deprecated syntax/features
    - offensive: Inappropriate content
    
    Requires authentication.
    """
    from sqlalchemy import text
    
    # Validate question exists
    question = db.query(QuestionBank).filter(
        QuestionBank.id == payload.question_id
    ).first()
    
    if not question:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Question {payload.question_id} not found"
        )
    
    # Validate report reason
    valid_reasons = ["incorrect_answer", "typo", "unclear", "outdated", "offensive"]
    if payload.report_reason not in valid_reasons:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid report reason. Must be one of: {', '.join(valid_reasons)}"
        )
    
    # Create report
    report_id = str(uuid.uuid4())
    
    db.execute(text("""
        INSERT INTO question_reports (
            id, question_id, reported_by, report_reason, description, status, created_at
        ) VALUES (
            :id, :question_id, :reported_by, :reason, :description, 'pending', NOW()
        )
    """), {
        "id": report_id,
        "question_id": payload.question_id,
        "reported_by": current_user["id"],
        "reason": payload.report_reason,
        "description": payload.description
    })
    
    db.commit()
    
    return QuestionReportResponse(
        report_id=report_id,
        message=f"Question reported successfully. Report ID: {report_id[:8]}...",
        status="pending"
    )


@router.get("/analytics/{question_id}", response_model=QuestionAnalyticsResponse)
async def get_question_analytics(
    question_id: str,
    current_user: dict = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Get analytics for a specific question.
    
    Returns:
    - Usage statistics (how many times used)
    - Accuracy rate (% of students who got it correct)
    - Average time spent
    - Quality metrics
    
    Requires authentication.
    """
    from sqlalchemy import text, func
    
    # Get question
    question = db.query(QuestionBank).filter(
        QuestionBank.id == question_id
    ).first()
    
    if not question:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Question {question_id} not found"
        )
    
    # Get usage statistics from user_question_history
    usage_stats = db.execute(text("""
        SELECT 
            COUNT(*) as usage_count,
            SUM(CASE WHEN was_correct THEN 1 ELSE 0 END) as correct_count,
            AVG(time_spent_seconds) as avg_time,
            MAX(attempted_at) as last_used
        FROM user_question_history
        WHERE question_id = :qid
    """), {"qid": question_id}).fetchone()
    
    usage_count = usage_stats[0] or 0
    correct_count = usage_stats[1] or 0
    avg_time = float(usage_stats[2]) if usage_stats[2] else 0.0
    last_used = usage_stats[3]
    
    accuracy_rate = (correct_count / usage_count * 100) if usage_count > 0 else 0.0
    
    return QuestionAnalyticsResponse(
        question_id=question_id,
        usage_count=usage_count,
        total_attempts=usage_count,
        correct_attempts=correct_count,
        accuracy_rate=round(accuracy_rate, 2),
        avg_time_spent=round(avg_time, 2),
        difficulty_rating=question.difficulty,
        quality_score=question.quality_score or 0.5,
        is_verified=question.is_verified,
        created_at=question.created_at.isoformat() if question.created_at else "",
        last_used_at=last_used.isoformat() if last_used else None
    )


@router.get("/analytics/summary", response_model=QuestionAnalyticsSummaryResponse)
async def get_question_analytics_summary(
    language_id: Optional[str] = None,
    mapping_id: Optional[str] = None,
    current_user: dict = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
):
    """
    Get summary analytics across all questions.
    
    Optional filters:
    - language_id: Filter by programming language
    - mapping_id: Filter by curriculum topic
    
    Requires admin authentication.
    """
    from sqlalchemy import text
    
    # Build query with optional filters
    filter_clause = ""
    params = {}
    
    if language_id:
        filter_clause += " AND q.language_id = :lang_id"
        params["lang_id"] = language_id
    
    if mapping_id:
        filter_clause += " AND q.mapping_id = :map_id"
        params["map_id"] = mapping_id
    
    # Get summary statistics
    summary = db.execute(text(f"""
        SELECT 
            COUNT(*) as total_questions,
            SUM(CASE WHEN is_verified THEN 1 ELSE 0 END) as verified_count,
            SUM(CASE WHEN NOT is_verified THEN 1 ELSE 0 END) as unverified_count
        FROM question_bank q
        WHERE 1=1 {filter_clause}
    """), params).fetchone()
    
    # Get usage statistics
    usage = db.execute(text(f"""
        SELECT 
            COUNT(DISTINCT h.question_id) as used_questions,
            COUNT(*) as total_usage,
            AVG(CASE WHEN h.was_correct THEN 100.0 ELSE 0.0 END) as avg_accuracy
        FROM user_question_history h
        JOIN question_bank q ON h.question_id = q.id
        WHERE 1=1 {filter_clause}
    """), params).fetchone()
    
    # Get low quality questions (quality score < 0.5)
    low_quality = db.execute(text(f"""
        SELECT id
        FROM question_bank q
        WHERE quality_score < 0.5 {filter_clause}
        ORDER BY quality_score ASC
        LIMIT 10
    """), params).fetchall()
    
    # Get questions needing review (unverified or reported)
    needs_review = db.execute(text(f"""
        SELECT COUNT(DISTINCT q.id)
        FROM question_bank q
        LEFT JOIN question_reports r ON q.id = r.question_id AND r.status = 'pending'
        WHERE (q.is_verified = FALSE OR r.id IS NOT NULL) {filter_clause}
    """), params).fetchone()
    
    return QuestionAnalyticsSummaryResponse(
        total_questions=summary[0] or 0,
        verified_count=summary[1] or 0,
        unverified_count=summary[2] or 0,
        total_usage=usage[1] or 0,
        avg_accuracy_rate=round(usage[2] or 0.0, 2),
        questions_needing_review=needs_review[0] or 0,
        low_quality_questions=[row[0] for row in low_quality]
    )

