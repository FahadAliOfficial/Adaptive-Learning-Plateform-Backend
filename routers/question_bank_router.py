"""
Question Bank API Endpoints
Provides REST API for question generation, selection, and admin review.
"""
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, status
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


router = APIRouter(prefix="/question-bank", tags=["Question Bank"])


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
async def generate_questions(
    request: GenerateRequest,
    background_tasks: BackgroundTasks,
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
    if request.language_id not in ["python_3", "javascript_es6", "java_17", "cpp_20", "go_1_21"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported language: {request.language_id}"
        )
    
    # Generate task ID
    task_id = str(uuid.uuid4())
    
    # Schedule background generation
    background_tasks.add_task(
        _background_generate,
        topic=request.topic,
        language_id=request.language_id,
        mapping_id=request.mapping_id,
        difficulty=request.difficulty,
        count=request.count,
        sub_topic=request.sub_topic,
        task_id=task_id
    )
    
    # Estimate time (1-2 seconds per question with OpenAI API)
    estimated_time = request.count * 1.5
    
    return GenerateResponse(
        task_id=task_id,
        message=f"Generation started. Creating {request.count} questions for '{request.topic}'.",
        estimated_time_seconds=int(estimated_time)
    )


@router.post("/select", response_model=SelectResponse)
async def select_questions(
    request: SelectRequest,
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
        user_id=request.user_id,
        language_id=request.language_id,
        mapping_id=request.mapping_id,
        target_difficulty=request.target_difficulty,
        count=request.count,
        difficulty_tolerance=request.difficulty_tolerance
    )
    
    # Get warehouse status for this topic
    warehouse_status = selector.get_warehouse_status(
        language_id=request.language_id,
        mapping_id=request.mapping_id,
        difficulty=request.target_difficulty,
        difficulty_tolerance=request.difficulty_tolerance
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
    request: AdminReviewRequest,
    db: Session = Depends(get_db)
):
    """
    Admin endpoint to approve or reject generated questions.
    
    Actions:
    - 'approve': Mark as verified (can be used in exams)
    - 'reject': Delete from database
    
    Requires admin authentication (TODO: Add auth middleware)
    """
    # Get question
    question = db.query(QuestionBank).filter(
        QuestionBank.id == request.question_id
    ).first()
    
    if not question:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Question {request.question_id} not found"
        )
    
    if request.action == "approve":
        question.is_verified = True
        question.review_notes = request.reviewer_notes
        db.commit()
        
        return AdminReviewResponse(
            question_id=request.question_id,
            action="approve",
            message=f"Question {request.question_id[:8]} approved and verified"
        )
    
    elif request.action == "reject":
        db.delete(question)
        db.commit()
        
        return AdminReviewResponse(
            question_id=request.question_id,
            action="reject",
            message=f"Question {request.question_id[:8]} rejected and deleted"
        )
    
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid action: {request.action}. Use 'approve' or 'reject'"
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
