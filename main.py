"""
FYP Backend API - Adaptive Learning System with Question Bank
Integrates grading, state vector, and AI-powered question generation.
"""

from fastapi import FastAPI, Depends, HTTPException, status, Request, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import Optional

from services.schemas import (
    ExamSubmissionPayload, 
    MasteryUpdateResponse,
    StateVectorRequest,
    StateVectorResponse,
    UserRegistrationPayload,
    UserRegistrationResponse,
    ExamStartRequest,
    ExamStartResponse
)
from services.grading_service import GradingService
from services.state_vector_service import StateVectorGenerator
from services.user_service import UserService
from services.review_scheduler import ReviewScheduler
from services.pattern_analyzer import PatternAnalyzer
from services.config import get_config
from services.auth import get_current_user, get_current_active_user

# ✅ Import from centralized database.py
from database import get_db, engine, Base, SessionLocal

import os
from dotenv import load_dotenv
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

# Load environment variables
load_dotenv()

# Import models to register with Base (for table creation)
import models.question_bank  # This registers QuestionBank and UserQuestionHistory tables

# Import routers
from routers import question_bank_router
from routers import analytics_router
from routers import auth_router
from routers import rl_router
from routers import admin_router
from routers import user_languages_router

app = FastAPI(
    title="FYP Backend API - Adaptive Learning",
    version="2.0",
    docs_url="/api/docs",        # Swagger UI at http://localhost:8000/api/docs
    redoc_url="/api/redoc",      # ReDoc at http://localhost:8000/api/redoc
    description="""
    🎓 **Adaptive Learning System API**
    
    ## Features
    - 🔐 JWT Authentication
    - 📝 AI-Powered Question Generation (OpenAI GPT-4o-mini)
    - 📊 Adaptive Exam System with RL Recommendations
    - 🤖 Multi-Agent RL (A2C, DQN, PPO)
    - 📈 Multi-Level Analytics
    - ⚠️ Question Reporting System
    - 📉 Performance Analytics
    
    ## Authentication
    Most endpoints require a valid JWT token in the Authorization header:
    ```
    Authorization: Bearer <your_access_token>
    ```
    """
)

# CORS Configuration - Allow frontend to connect
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",      # Next.js default
        "http://localhost:5173",      # Vite default
        "http://localhost:4200",      # Angular default
        "http://127.0.0.1:3000",      # Next.js (127.0.0.1)
        "http://127.0.0.1:5173",
        "http://127.0.0.1:4200",
    ],
    allow_credentials=True,
    allow_methods=["*"],              # Allow all HTTP methods (GET, POST, PUT, DELETE, etc.)
    allow_headers=["*"],              # Allow all headers (Authorization, Content-Type, etc.)
    expose_headers=["*"],             # Expose all headers to frontend
)

# Rate limiting setup
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Register authentication routes
app.include_router(auth_router.router)

# Register question bank routes
app.include_router(question_bank_router.router)

# Register analytics routes
app.include_router(analytics_router.router)

# Register RL routes
app.include_router(rl_router.router)

# Register admin routes
app.include_router(admin_router.router)

# Register user languages routes
app.include_router(user_languages_router.router)


@app.get("/")
async def root():
    """Root endpoint - Health check"""
    return {
        "status": "ok",
        "message": "FYP Backend API is running",
        "version": "1.0.0",
        "docs": "/docs"
    }


@app.get("/api/health")
async def health_check():
    """Health check endpoint for monitoring"""
    return {
        "status": "healthy",
        "database": "connected",
        "timestamp": "2026-02-07T00:00:00Z"
    }


@app.get("/curriculum/all")
async def get_curriculum():
    """
    Get complete curriculum data for all languages.
    Used by admin interfaces to populate topic/subtopic dropdowns.
    """
    import json
    from pathlib import Path
    
    curriculum_path = Path(__file__).parent / "core" / "final_curriculum.json"
    
    try:
        with open(curriculum_path, 'r', encoding='utf-8') as f:
            curriculum_data = json.load(f)
        return curriculum_data
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to load curriculum: {str(e)}"
        )


@app.on_event("startup")
async def startup():
    """
    Initialize database tables and load RL models on startup.
    Only creates tables if they don't exist (safe for production).
    """
    Base.metadata.create_all(bind=engine)
    print("✅ Database tables initialized (QuestionBank, UserQuestionHistory)")
    
    # Load RL models
    print("\n🤖 Loading RL models...")
    from services.rl.rl_service import get_rl_service
    rl_service = get_rl_service()
    load_status = rl_service.load_models(device="auto")
    
    if all(load_status.values()):
        print("✅ All RL models loaded successfully")
    elif any(load_status.values()):
        print("⚠️ Some RL models loaded - baseline fallback available")
    else:
        print("⚠️ No RL models loaded - using baseline only")


# Dependency: Database Session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# Dependency injection for database sessions
def get_db_dependency():
    """
    DEPRECATED: Use get_db from database.py instead.
    This is kept for backward compatibility with existing routes.
    """
    return get_db()


@app.post("/api/exam/start", response_model=ExamStartResponse)
@limiter.limit("20/minute")  # Max 20 session starts per minute
async def start_exam_session(
    request: Request,
    payload: ExamStartRequest,
    current_user: dict = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Phase 3 #13: Start a new exam session.
    Creates a session record in 'started' state without scores.
    
    **Requires:** Valid JWT access token
    
    Workflow:
    1. Verify user_id matches authenticated user
    2. Generate session_id and create exam_sessions record
    3. Return session_id to frontend for later submission
    """
    # Verify user_id matches authenticated user
    if payload.user_id != current_user["id"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot start session for another user"
        )
    
    try:
        import uuid
        from datetime import datetime
        
        session_id = str(uuid.uuid4())
        started_at = datetime.now()
        
        # Create session in 'started' state
        db.execute(text("""
            INSERT INTO exam_sessions (
                id, user_id, language_id, major_topic_id, 
                session_type, session_status, started_at, created_at
            )
            VALUES (
                :session_id, :user_id, :language_id, :major_topic_id,
                :session_type, 'started', :started_at, :created_at
            )
        """), {
            "session_id": session_id,
            "user_id": payload.user_id,
            "language_id": payload.language_id,
            "major_topic_id": payload.major_topic_id,
            "session_type": payload.session_type,
            "started_at": started_at,
            "created_at": started_at
        })
        db.commit()
        
        return ExamStartResponse(
            session_id=session_id,
            started_at=started_at.isoformat()
        )
    
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create session: {str(e)}"
        )


@app.post("/api/exam/submit", response_model=MasteryUpdateResponse)
@limiter.limit("10/minute")  # Max 10 exam submissions per minute
async def submit_exam(
    request: Request,
    payload: ExamSubmissionPayload,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Scenario B: Submission Cycle
    Process exam results and update mastery scores.
    
    **Requires:** Valid JWT access token
    
    Workflow:
    1. Validate payload (Pydantic handles this)
    2. Verify session exists and belongs to user
    3. Verify user owns the submission (user_id matches token)
    4. Process submission through GradingService
    5. Return updated mastery + recommendations
    """
    # Verify user_id matches authenticated user
    if payload.user_id != current_user["id"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot submit exam for another user"
        )
    
    # Verify session exists and belongs to user
    session_check = db.execute(text("""
        SELECT user_id, session_status FROM exam_sessions WHERE id = :session_id
    """), {"session_id": payload.session_id}).fetchone()
    
    if not session_check:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found"
        )
    
    if session_check[0] != payload.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Session belongs to another user"
        )
    
    if session_check[1] != 'started':
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Session already {session_check[1]}"
        )
    
    try:
        grading_service = GradingService(db)
        result = grading_service.process_submission(payload, background_tasks)
        return result
    
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Processing failed: {str(e)}"
        )


@app.get("/api/exam/analysis/{session_id}")
async def get_exam_analysis(
    session_id: str,
    current_user: dict = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Get LLM-generated exam analysis (personalized feedback).
    Analysis is generated asynchronously after exam submission.
    
    **Requires:** Valid JWT access token
    
    Returns:
        {
            "status": "completed" | "generating" | "pending" | "failed",
            "bullets": ["...", "...", ...],  // Max 5
            "generated_at": "2026-02-06T12:30:00",
            "error": null
        }
    """
    # Verify session belongs to user
    check = db.execute(text("""
        SELECT es.user_id
        FROM exam_sessions es
        WHERE es.id = :sid
    """), {"sid": session_id}).fetchone()
    
    if not check:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found"
        )
    
    if check[0] != current_user["id"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Session belongs to another user"
        )
    
    # Get analysis
    analysis = db.execute(text("""
        SELECT 
            analysis_status,
            analysis_bullets,
            analysis_generated_at,
            analysis_error
        FROM exam_details
        WHERE session_id = :sid
    """), {"sid": session_id}).fetchone()
    
    if not analysis:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Analysis not found"
        )
    
    return {
        "status": analysis[0],
        "bullets": analysis[1],  # PostgreSQL array → Python list
        "generated_at": analysis[2].isoformat() if analysis[2] else None,
        "error": analysis[3]
    }


@app.get("/api/exam/results/{session_id}")
async def get_exam_results(
    session_id: str,
    current_user: dict = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Get full exam results including questions snapshot, strong topics,
    error patterns, and LLM-generated recommendations.

    **Requires:** Valid JWT access token
    """
    import json

    # Verify session belongs to user
    session_check = db.execute(text("""
        SELECT user_id
        FROM exam_sessions
        WHERE id = :sid
    """), {"sid": session_id}).fetchone()

    if not session_check:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found"
        )

    if session_check[0] != current_user["id"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Session belongs to another user"
        )

    result = db.execute(text("""
        SELECT 
            es.session_type,
            es.language_id,
            es.major_topic_id,
            es.overall_score,
            es.time_taken_seconds,
            ed.questions_snapshot,
            ed.recommendations,
            ed.analysis_status,
            ed.analysis_bullets
        FROM exam_sessions es
        JOIN exam_details ed ON ed.session_id = es.id
        WHERE es.id = :sid
    """), {"sid": session_id}).fetchone()

    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Exam details not found"
        )

    session_type = result[0]
    language_id = result[1]
    major_topic_id = result[2]
    overall_score = result[3] or 0.0
    time_taken_seconds = result[4] or 0
    questions_raw = result[5]
    recommendations_raw = result[6]
    analysis_status = result[7]
    analysis_bullets = result[8]

    if isinstance(questions_raw, str):
        questions_data = json.loads(questions_raw)
    else:
        questions_data = questions_raw or {}

    questions = questions_data.get("questions", []) if isinstance(questions_data, dict) else []

    # Compute strong topics
    config = get_config()
    topic_stats = {}
    for q in questions:
        # Get topic name: prefer sub_topic, fallback to mapping name from config
        topic = q.get("sub_topic")
        if not topic or topic == "Unknown":
            # Try to get a better name from config using language_id and major_topic_id
            mapping_info = config.mapping_to_topics.get(major_topic_id, {}).get(language_id, {})
            topic = mapping_info.get("name") or major_topic_id
        
        if topic not in topic_stats:
            topic_stats[topic] = {"correct": 0, "total": 0}
        topic_stats[topic]["total"] += 1
        if q.get("is_correct"):
            topic_stats[topic]["correct"] += 1

    topic_scores = [
        {
            "name": topic,
            "accuracy": round((data["correct"] / data["total"]) * 100)
        }
        for topic, data in topic_stats.items()
        if data["total"] > 0
    ]
    topic_scores.sort(key=lambda x: x["accuracy"], reverse=True)

    strong_topics = [t for t in topic_scores if t["accuracy"] >= 70]
    if not strong_topics:
        strong_topics = topic_scores[:3]

    # Error patterns summary
    error_counts = {}
    for q in questions:
        error_type = q.get("error_type")
        if error_type:
            error_counts[error_type] = error_counts.get(error_type, 0) + 1

    error_patterns = [
        {"error_type": k, "count": v}
        for k, v in error_counts.items()
    ]

    # Recommendations payload
    if isinstance(recommendations_raw, str):
        recommendations = json.loads(recommendations_raw)
    else:
        recommendations = recommendations_raw or {}

    resources = recommendations.get("resources", []) if isinstance(recommendations, dict) else []

    return {
        "session_id": session_id,
        "session_type": session_type,
        "language_id": language_id,
        "major_topic_id": major_topic_id,
        "overall_score": overall_score,
        "accuracy": round(overall_score * 100),
        "time_taken_seconds": time_taken_seconds,
        "questions": questions,
        "strong_topics": strong_topics,
        "error_patterns": error_patterns,
        "recommendations": resources,
        "analysis_status": analysis_status,
        "analysis_bullets": analysis_bullets
    }


@app.get("/api/sessions/history")
async def get_session_history(
    current_user: dict = Depends(get_current_active_user),
    db: Session = Depends(get_db),
    language_id: Optional[str] = None,
    session_type: Optional[str] = None,
    limit: int = 50,
    offset: int = 0
):
    """
    Get user's exam session history with optional filters.
    
    **Query Parameters:**
    - language_id: Filter by language
    - session_type: Filter by type (practice, exam, review)
    - limit: Max sessions to return (default 50)
    - offset: Pagination offset
    
    **Requires:** Valid JWT access token
    """
    user_id = current_user["id"]
    
    # Build query with filters
    query = """
        SELECT 
            es.id,
            es.session_type,
            es.language_id,
            es.major_topic_id,
            es.overall_score,
            es.difficulty_assigned,
            es.time_taken_seconds,
            es.created_at,
            es.completed_at,
            (
                SELECT COUNT(*)
                FROM jsonb_array_elements(ed.questions_snapshot->'questions') AS q
            ) as question_count,
            (
                SELECT COUNT(*)
                FROM jsonb_array_elements(ed.questions_snapshot->'questions') AS q
                WHERE (q->>'is_correct')::boolean = true
            ) as correct_count
        FROM exam_sessions es
        LEFT JOIN exam_details ed ON ed.session_id = es.id
        WHERE es.user_id = :user_id
          AND es.session_status = 'completed'
    """
    
    params = {"user_id": user_id}
    
    if language_id:
        query += " AND es.language_id = :language_id"
        params["language_id"] = language_id
    
    if session_type:
        query += " AND es.session_type = :session_type"
        params["session_type"] = session_type
    
    query += " ORDER BY es.created_at DESC LIMIT :limit OFFSET :offset"
    params["limit"] = limit
    params["offset"] = offset
    
    sessions = db.execute(text(query), params).fetchall()
    
    # Get config for topic names
    config = get_config()
    
    results = []
    for session in sessions:
        # Get topic name from config
        mapping_info = config.mapping_to_topics.get(session[3], {}).get(session[2], {})
        topic_name = mapping_info.get("name") or session[3]
        
        results.append({
            "session_id": session[0],
            "session_type": session[1],
            "language_id": session[2],
            "major_topic_id": session[3],
            "topic_name": topic_name,
            "overall_score": session[4] or 0.0,
            "accuracy": round((session[4] or 0.0) * 100),
            "difficulty": session[5] or 0.5,
            "time_taken_seconds": session[6] or 0,
            "created_at": session[7].isoformat() if session[7] else None,
            "completed_at": session[8].isoformat() if session[8] else None,
            "question_count": session[9] or 0,
            "correct_count": session[10] or 0
        })
    
    # Get total count for pagination
    count_query = text("""
        SELECT COUNT(*)
        FROM exam_sessions
        WHERE user_id = :user_id
          AND session_status = 'completed'
    """ + (" AND language_id = :language_id" if language_id else "") +
          (" AND session_type = :session_type" if session_type else ""))
    
    total_count = db.execute(count_query, params).scalar()
    
    return {
        "sessions": results,
        "total_count": total_count,
        "limit": limit,
        "offset": offset
    }


@app.post("/api/rl/state-vector", response_model=StateVectorResponse)
async def get_state_vector(
    request: StateVectorRequest,
    current_user: dict = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Scenario A: Request Cycle
    Generate RL state vector for decision-making.
    
    **Requires:** Valid JWT access token
    
    Workflow:
    1. Validate user_id and language_id
    2. Generate 27-dimensional state vector
    3. Return vector + human-readable metadata
    """
    import logging
    logger = logging.getLogger(__name__)
    
    try:
        logger.info(f"[API] State vector request for user {request.user_id[:8]}... language {request.language_id}")
        vector_service = StateVectorGenerator(db)
        result = vector_service.generate_vector(request)
        logger.info(f"[API] State vector generated successfully")
        return result
    
    except Exception as e:
        logger.error(f"[API] State vector generation failed: {type(e).__name__}: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"State vector generation failed: {str(e)}"
        )


@app.get("/api/health")
async def health_check():
    """Simple health check endpoint."""
    return {
        "status": "healthy",
        "phase": "2D",
        "version": "2.2",
        "features": ["adaptive_difficulty", "temporal_predictions", "spaced_repetition", "error_pattern_analysis"]
    }


@app.get("/api/reviews/due")
@limiter.limit("10/minute")  # Max 10 requests per minute
async def get_due_reviews(
    request: Request,
    user_id: str,
    language_id: str = None,
    current_user: dict = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Phase 2C: Get all reviews due for a user.
    
    **Requires:** Valid JWT access token
    
    Returns topics that need review based on spaced repetition schedule.
    Sorted by priority (most urgent first), then by date.
    
    Example:
        GET /api/reviews/due?user_id=abc-123&language_id=python_3
    
    Response:
        {
            "user_id": "abc-123",
            "total_due": 3,
            "reviews": [
                {
                    "mapping_id": "UNIV_LOOP",
                    "language_id": "python_3",
                    "current_mastery": 0.68,
                    "due_date": "2026-01-25T10:00:00Z",
                    "priority": 3,
                    "days_overdue": 2
                }
            ]
        }
    """
    # Verify user can only access their own data
    if user_id != current_user["id"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot access other user's review schedule"
        )
    
    try:
        scheduler = ReviewScheduler(db)
        due_reviews = scheduler.get_due_reviews(user_id, language_id)
        
        return {
            "success": True,
            "user_id": user_id,
            "total_due": len(due_reviews),
            "reviews": due_reviews
        }
    
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch due reviews: {str(e)}"
        )


@app.get("/api/reviews/upcoming")
@limiter.limit("10/minute")  # Max 10 requests per minute
async def get_upcoming_reviews(
    request: Request,
    user_id: str,
    language_id: str = None,
    days_ahead: int = 7,
    current_user: dict = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Phase 2C: Get reviews scheduled in the next N days.
    
    **Requires:** Valid JWT access token
    
    Helps users plan their study schedule by showing upcoming reviews.
    
    Example:
        GET /api/reviews/upcoming?user_id=abc-123&days_ahead=7
    
    Response:
        {
            "user_id": "abc-123",
            "days_ahead": 7,
            "upcoming_count": 5,
            "reviews": [
                {
                    "mapping_id": "UNIV_VAR",
                    "language_id": "python_3",
                    "due_date": "2026-01-28T10:00:00Z",
                    "priority": 2,
                    "current_mastery": 0.82,
                    "interval_days": 7
                }
            ]
        }
    """
    # Verify user can only access their own data
    if user_id != current_user["id"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot access other user's review schedule"
        )
    
    try:
        scheduler = ReviewScheduler(db)
        upcoming = scheduler.get_upcoming_reviews(user_id, language_id, days_ahead)
        
        return {
            "success": True,
            "user_id": user_id,
            "days_ahead": days_ahead,
            "upcoming_count": len(upcoming),
            "reviews": upcoming
        }
    
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch upcoming reviews: {str(e)}"
        )


@app.get("/api/analytics/error-patterns")
@limiter.limit("10/minute")  # Max 10 requests per minute
async def get_error_patterns(
    request: Request,
    user_id: str,
    language_id: str,
    window_size: int = 50,
    current_user: dict = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Phase 2D: Get advanced error pattern analysis for a user.
    
    **Requires:** Valid JWT access token
    
    Returns personalized error insights, trends, and remediation plan.
    Uses hybrid scoring: frequency × severity for prioritization.
    
    Example:
        GET /api/analytics/error-patterns?user_id=abc-123&language_id=python_3
    
    Response:
        {
            "success": true,
            "top_errors": [
                {
                    "error_type": "OFF_BY_ONE_ERROR",
                    "count": 12,
                    "severity": 0.5,
                    "priority_score": 6.0,
                    "category": "LOOP_ERRORS",
                    "remediation_boost": 0.12,
                    "suggested_practice": "Loop iterates one time too many or too few"
                }
            ],
            "error_trends": {
                "improving": ["MISSING_SEMICOLON"],
                "persistent": ["OFF_BY_ONE_ERROR", "INDEX_OUT_OF_BOUNDS"]
            },
            "recommended_remediation": [
                "1. Off By One Error (MEDIUM priority, occurred 12x) - Loop iterates one time too many or too few"
            ],
            "total_errors_analyzed": 45
        }
    """
    # Verify user can only access their own data
    if user_id != current_user["id"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot access other user's error patterns"
        )
    
    try:
        analyzer = PatternAnalyzer(db)
        analysis = analyzer.analyze_user_patterns(user_id, language_id, window_size)
        
        return {
            "success": True,
            **analysis
        }
    
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to analyze error patterns: {str(e)}"
        )


@app.get("/api/progress/prediction")
@limiter.limit("10/minute")  # Max 10 prediction requests per minute
async def get_progress_prediction(
    request: Request,
    user_id: str,
    language_id: str,
    mapping_id: str,
    current_user: dict = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Phase 2B Feature #17: Get time-to-mastery prediction for a topic.
    
    **Requires:** Valid JWT access token
    
    Returns estimated hours and sessions needed to reach 0.75 mastery,
    based on user's learning velocity and config baselines.
    
    Example:
        GET /api/progress/prediction?user_id=abc-123&language_id=python_3&mapping_id=UNIV_LOOP
    
    Response:
        {
            "mapping_id": "UNIV_LOOP",
            "current_mastery": 0.45,
            "target_mastery": 0.75,
            "prediction": {
                "estimated_hours": 3.2,
                "estimated_sessions": 5,
                "current_velocity": 0.094,
                "confidence": 0.6
            }
        }
    """
    # Verify user can only access their own data
    if user_id != current_user["id"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot access other user's progress predictions"
        )
    
    try:
        from services.grading_service import GradingService
        
        grading_service = GradingService(db)
        
        # Get current mastery
        current_query = text("""
            SELECT mastery_score FROM student_state
            WHERE user_id = :u AND language_id = :l AND mapping_id = :m
        """)
        current = db.execute(current_query, {
            "u": user_id, 
            "l": language_id, 
            "m": mapping_id
        }).scalar() or 0.0
        
        # Get prediction
        prediction = grading_service._predict_time_to_mastery(
            user_id, language_id, mapping_id, current
        )
        
        return {
            "success": True,
            "mapping_id": mapping_id,
            "language_id": language_id,
            "current_mastery": round(current, 3),
            "target_mastery": 0.75,
            "prediction": prediction
        }
    
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Prediction failed: {str(e)}"
        )


@app.post("/api/user/register", response_model=UserRegistrationResponse)
@limiter.limit("5/minute")  # Max 5 registrations per minute per IP
async def register_user(
    request: Request,
    payload: UserRegistrationPayload,
    db: Session = Depends(get_db)
):
    """
    Register a new user and initialize their knowledge state.
    
    Experience levels:
    - beginner: Starts from UNIV_SYN_LOGIC (topic 1)
    - intermediate: Assumed mastery of topics 1-4, starts at UNIV_LOOP
    - advanced: Assumed mastery of topics 1-7, starts at UNIV_OOP
    """
    try:
        user_service = UserService(db)
        return user_service.register_user(payload)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Registration failed: {str(e)}"
        )


# Example usage documentation
"""
EXAMPLE REQUESTS:

1. Submit Exam (Scenario B):
POST /api/exam/submit
{
    "user_id": "550e8400-e29b-41d4-a716-446655440000",
    "language_id": "python_3",
    "major_topic_id": "PY_VAR_01",
    "session_type": "practice",
    "total_time_seconds": 300,
    "results": [
        {
            "q_id": "q_abc123",
            "sub_topic": "Dynamic Typing",
            "difficulty": 0.5,
            "is_correct": true,
            "time_spent": 45.2,
            "expected_time": 60.0,
            "error_type": null
        },
        {
            "q_id": "q_xyz789",
            "sub_topic": "String Formatting",
            "difficulty": 0.7,
            "is_correct": false,
            "time_spent": 85.3,
            "expected_time": 70.0,
            "error_type": "TYPE_MISMATCH"
        }
    ]
}

RESPONSE:
{
    "success": true,
    "session_id": "abc-def-ghi",
    "accuracy": 0.667,
    "fluency_ratio": 1.15,
    "new_mastery_score": 0.623,
    "synergies_applied": ["UNIV_COND (+0.10)"],
    "soft_gate_violations": [],
    "recommendations": [
        "📈 Good progress. Practice more to solidify understanding.",
        "🔄 Review needed for: UNIV_SYN_PREC"
    ]
}

---

2. Get State Vector (Scenario A):
POST /api/rl/state-vector
{
    "user_id": "550e8400-e29b-41d4-a716-446655440000",
    "language_id": "python_3"
}

RESPONSE:
{
    "state_vector": [1.0, 0.0, 0.0, 0.0, 0.0, 0.45, 0.62, 0.38, ...],
    "metadata": {
        "user_id": "550e8400-e29b-41d4-a716-446655440000",
        "language": "python_3",
        "strongest_topic": {"id": "UNIV_VAR", "mastery": 0.623},
        "weakest_topic": {"id": "UNIV_OOP", "mastery": 0.12},
        "needs_review": ["UNIV_SYN_PREC", "UNIV_COND"],
        "overall_mastery_avg": 0.412,
        "last_session_accuracy": 0.667,
        "stability_score": 0.823,
        "days_since_practice": 2,
        "gate_readiness": 0.75
    }
}
"""

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
