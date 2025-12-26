"""
FYP Backend API - Adaptive Learning System with Question Bank
Integrates grading, state vector, and AI-powered question generation.
"""

from fastapi import FastAPI, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session

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

# ✅ Import from centralized database.py
from database import get_db, engine, Base

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

app = FastAPI(title="FYP Backend API - Question Bank", version="2.0")

# Rate limiting setup
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Register question bank routes
app.include_router(question_bank_router.router)


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
    db: Session = Depends(get_db)
):
    """
    Scenario B: Submission Cycle
    Process exam results and update mastery scores.
    
    Workflow:
    1. Validate payload (Pydantic handles this)
    2. Process submission through GradingService
    3. Return updated mastery + recommendations
    """
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
    db: Session = Depends(get_db)
):
    """
    Scenario A: Request Cycle
    Generate RL state vector for decision-making.
    
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
        "phase": "1",
        "version": "1.0"
    }


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
