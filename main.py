"""
Example FastAPI integration for Phase 1 services.
This demonstrates how to wire up the grading and state vector services.
"""

from fastapi import FastAPI, Depends, HTTPException, status
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from contextlib import contextmanager

from services.schemas import (
    ExamSubmissionPayload, 
    MasteryUpdateResponse,
    StateVectorRequest,
    StateVectorResponse
)
from services.grading_service import GradingService
from services.state_vector_service import StateVectorGenerator

# Database setup
DATABASE_URL = "postgresql://user:password@localhost:5432/fyp_db"
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

app = FastAPI(title="FYP Phase 1 API", version="1.0")


# Dependency: Database Session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@app.post("/api/exam/submit", response_model=MasteryUpdateResponse)
async def submit_exam(
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
