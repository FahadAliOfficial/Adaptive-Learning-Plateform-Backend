"""
FYP Backend API - Adaptive Learning System with Question Bank
Integrates grading, state vector, and AI-powered question generation.
"""

from fastapi import FastAPI, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from sqlalchemy import text

from services.schemas import (
    ExamSubmissionPayload, 
    MasteryUpdateResponse,
    StateVectorRequest,
    StateVectorResponse,
    UserRegistrationPayload,
    UserRegistrationResponse
)
from services.grading_service import GradingService
from services.state_vector_service import StateVectorGenerator
from services.user_service import UserService
from services.review_scheduler import ReviewScheduler
from services.pattern_analyzer import PatternAnalyzer
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

app = FastAPI(title="FYP Backend API - Adaptive Learning", version="2.0")

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


@app.on_event("startup")
async def startup():
    """
    Initialize database tables on startup.
    Only creates tables if they don't exist (safe for production).
    """
    Base.metadata.create_all(bind=engine)
    print("✅ Database tables initialized (QuestionBank, UserQuestionHistory)")


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


@app.post("/api/exam/submit", response_model=MasteryUpdateResponse)
@limiter.limit("10/minute")  # Max 10 exam submissions per minute
async def submit_exam(
    request: Request,
    payload: ExamSubmissionPayload,
    current_user: dict = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Scenario B: Submission Cycle
    Process exam results and update mastery scores.
    
    **Requires:** Valid JWT access token
    
    Workflow:
    1. Validate payload (Pydantic handles this)
    2. Verify user owns the submission (user_id matches token)
    3. Process submission through GradingService
    4. Return updated mastery + recommendations
    """
    # Verify user_id matches authenticated user
    if payload.user_id != current_user["id"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot submit exam for another user"
        )
    
    try:
        grading_service = GradingService(db)
        result = grading_service.process_submission(payload)
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
    try:
        vector_service = StateVectorGenerator(db)
        result = vector_service.generate_vector(request)
        return result
    
    except Exception as e:
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
    db: Session = Depends(get_db)
):
    """
    Phase 2C: Get all reviews due for a user.
    
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
    db: Session = Depends(get_db)
):
    """
    Phase 2C: Get reviews scheduled in the next N days.
    
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
    db: Session = Depends(get_db)
):
    """
    Phase 2D: Get advanced error pattern analysis for a user.
    
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
    db: Session = Depends(get_db)
):
    """
    Phase 2B Feature #17: Get time-to-mastery prediction for a topic.
    
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
