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
    selected_choice: str = Field(..., description="A, B, C, or D - student's selected answer")
    correct_choice: str = Field(..., description="A, B, C, or D - the correct answer")
    time_spent: float = Field(..., gt=0, description="Seconds taken to answer")
    expected_time: float = Field(..., gt=0, description="Expected time for this difficulty")
    error_type: Optional[str] = Field(None, description="Error pattern if incorrect (from error_pattern_taxonomy)")

    @validator('difficulty')
    def validate_difficulty(cls, v):
        if not (0.0 <= v <= 1.0):
            raise ValueError('Difficulty must be between 0.0 and 1.0')
        return round(v, 2)
    
    @validator('selected_choice', 'correct_choice')
    def validate_choice(cls, v):
        if v not in ['A', 'B', 'C', 'D']:
            raise ValueError('Choice must be A, B, C, or D')
        return v


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


class UserRegistrationPayload(BaseModel):
    """New user registration request."""
    email: str = Field(..., description="User email address")
    password: str = Field(..., min_length=6, description="User password (will be hashed)")
    language_id: Literal["python_3", "javascript_es6", "java_17", "cpp_20", "go_1_21"]
    experience_level: Literal["beginner", "intermediate", "advanced"] = Field(
        default="beginner",
        description="Self-reported experience level for initial state priming"
    )

    @validator('email')
    def validate_email(cls, v):
        if '@' not in v or '.' not in v:
            raise ValueError('Invalid email format')
        return v.lower()


class UserRegistrationResponse(BaseModel):
    """Response after successful user registration."""
    user_id: str
    message: str
    starting_topic: str = Field(..., description="Language-specific major_topic_id to start with")
    experience_level: str


# ==================== Authentication Schemas ====================

class LoginRequest(BaseModel):
    """User login request."""
    email: str = Field(..., description="User email address")
    password: str = Field(..., description="User password")

    @validator('email')
    def validate_email(cls, v):
        if '@' not in v or '.' not in v:
            raise ValueError('Invalid email format')
        return v.lower()


class LoginResponse(BaseModel):
    """Response after successful login."""
    access_token: str = Field(..., description="JWT access token")
    refresh_token: str = Field(..., description="JWT refresh token for getting new access tokens")
    token_type: str = Field(default="bearer", description="Token type")
    user_id: str
    email: str
    last_active_language: Optional[str] = None


class TokenRefreshRequest(BaseModel):
    """Request to refresh access token."""
    refresh_token: str = Field(..., description="Valid refresh token")


class TokenRefreshResponse(BaseModel):
    """Response with new access token."""
    access_token: str
    token_type: str = Field(default="bearer")


class UserProfile(BaseModel):
    """User profile data."""
    id: str
    email: str
    last_active_language: Optional[str] = None
    total_exams_taken: int = 0
    created_at: str  # ISO format timestamp


class PasswordChangeRequest(BaseModel):
    """Request to change password."""
    current_password: str = Field(..., description="Current password for verification")
    new_password: str = Field(..., min_length=6, description="New password")


class PasswordChangeResponse(BaseModel):
    """Response after password change."""
    success: bool
    message: str


# ==================== RL Recommendation Schemas ====================

class RecommendationRequest(BaseModel):
    """Request for RL curriculum recommendation."""
    user_id: str = Field(..., description="User UUID")
    language_id: Literal["python_3", "javascript_es6", "java_17", "cpp_20", "go_1_21"]
    strategy: Literal["ppo", "dqn", "a2c", "ensemble", "baseline"] = Field(
        default="a2c",
        description="RL model strategy to use for recommendation"
    )
    deterministic: bool = Field(
        default=True,
        description="Use deterministic policy (True for production, False for exploration)"
    )

    @validator('user_id')
    def validate_uuid(cls, v):
        try:
            return str(UUID(v))
        except ValueError:
            raise ValueError(f'Invalid UUID format for user_id: {v}')


class RecommendationResponse(BaseModel):
    """RL curriculum recommendation response with prerequisite validation."""
    mapping_id: str = Field(..., description="Universal topic ID (e.g., UNIV_VAR, UNIV_LOOP)")
    major_topic_id: str = Field(..., description="Language-specific topic ID (e.g., PY_VAR_01)")
    difficulty: float = Field(..., ge=0.0, le=1.0, description="Recommended difficulty tier")
    action_id: int = Field(..., description="RL action index (-1 for baseline)")
    strategy_used: str = Field(..., description="Strategy that generated this recommendation")
    confidence: Optional[float] = Field(None, description="Confidence score (0-1) for ensemble")
    metadata: dict = Field(..., description="Additional info: prerequisite checks, violations, etc.")


class HealthStatusResponse(BaseModel):
    """RL service health status."""
    service: str
    status: str = Field(..., description="'healthy' or 'degraded'")
    models_loaded: dict = Field(..., description="Status of each model (ppo, dqn, a2c)")
    environment_ready: bool
    available_strategies: List[str]


