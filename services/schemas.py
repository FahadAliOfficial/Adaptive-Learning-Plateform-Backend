"""
Pydantic models for Phase 1 request/response validation.
Aligned with final_curriculum.json and transition_map.json.
"""

from pydantic import BaseModel, Field, validator
from typing import List, Optional, Literal
from uuid import UUID


class QuestionResult(BaseModel):
    """Individual question result from a practice session."""
    q_id: str = Field(..., description="Question UUID from question_bank")
    sub_topic: str = Field(..., description="Exact sub_topic from curriculum")
    difficulty: float = Field(..., ge=0.0, le=1.0, description="Question difficulty weight")
    is_correct: bool = Field(..., description="Whether answer was correct")
    time_spent: float = Field(..., gt=0, description="Seconds taken to answer")
    expected_time: float = Field(..., gt=0, description="Expected time for this difficulty")
    error_type: Optional[str] = Field(None, description="Error pattern if incorrect (from error_pattern_taxonomy)")

    @validator('difficulty')
    def validate_difficulty(cls, v):
        if not (0.0 <= v <= 1.0):
            raise ValueError('Difficulty must be between 0.0 and 1.0')
        return round(v, 2)


class ExamSubmissionPayload(BaseModel):
    """Complete exam session submission from frontend."""
    user_id: str = Field(..., description="User UUID")
    language_id: Literal["python_3", "javascript_es6", "java_17", "cpp_20", "go_1_21"]
    major_topic_id: str = Field(..., description="e.g., 'PY_VAR_01', 'JS_FUNC_01'")
    session_type: Literal["diagnostic", "practice"] = Field(default="practice")
    results: List[QuestionResult] = Field(..., min_items=5, max_items=50)
    total_time_seconds: int = Field(..., gt=0, description="Total session duration")

    @validator('user_id')
    def validate_uuid(cls, v):
        try:
            UUID(v)
        except ValueError:
            raise ValueError('Invalid UUID format for user_id')
        return v

    @validator('major_topic_id')
    def validate_topic_format(cls, v):
        """Ensure format like PY_VAR_01, JS_FUNC_01, etc."""
        if not (v.count('_') >= 2 and v[-2:].isdigit()):
            raise ValueError(f'Invalid major_topic_id format: {v}')
        return v


class MasteryUpdateResponse(BaseModel):
    """Response after processing exam submission."""
    success: bool
    session_id: str
    accuracy: float
    fluency_ratio: float
    new_mastery_score: float
    synergies_applied: List[str]  # List of mapping_ids that received synergy boost
    soft_gate_violations: List[str]  # Topics attempted without prerequisites
    recommendations: List[str]  # Next topics to study


class StateVectorRequest(BaseModel):
    """Request for RL state vector generation."""
    user_id: str
    language_id: Literal["python_3", "javascript_es6", "java_17", "cpp_20", "go_1_21"]

    @validator('user_id')
    def validate_uuid(cls, v):
        try:
            # Normalize UUID format (ensures standard hyphenated lowercase)
            return str(UUID(v))
        except ValueError:
            raise ValueError(f'Invalid UUID format for user_id: {v}')


class StateVectorResponse(BaseModel):
    """RL-ready state representation (dynamic dimensions based on curriculum)."""
    state_vector: List[float] = Field(..., min_items=1)  # Dynamic size adapts to curriculum changes
    metadata: dict = Field(..., description="Human-readable state interpretation with prerequisites, transfer potential, and error patterns")
