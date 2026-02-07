"""
Pydantic models for Phase 1 request/response validation.
Aligned with final_curriculum.json and transition_map.json.
"""

from pydantic import BaseModel, Field, validator
from typing import List, Optional, Literal, Union
from uuid import UUID
import json
from pathlib import Path


# Load language IDs dynamically from curriculum
def _load_language_ids() -> List[str]:
    """Load available language IDs from final_curriculum.json"""
    curriculum_path = Path(__file__).parent.parent / "core" / "final_curriculum.json"
    
    try:
        with open(curriculum_path, 'r', encoding='utf-8') as f:
            curriculum = json.load(f)
            language_ids = [item["language_id"] for item in curriculum]
            return language_ids
    except Exception as e:
        # Fallback to hardcoded values if file cannot be loaded
        print(f"Warning: Could not load curriculum file, using fallback values. Error: {e}")
        return ["python_3", "javascript_es6", "java_17", "cpp_20", "go_1_21", "typescript_5"]


# Available language IDs (cached at module load)
AVAILABLE_LANGUAGES = _load_language_ids()

# Type alias for language IDs (for Pydantic validation)
# Note: Pydantic validates against the AVAILABLE_LANGUAGES list at runtime
LanguageIdType = str


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


class ExamStartRequest(BaseModel):
    """Request to start a new exam session."""
    user_id: str = Field(..., description="User UUID")
    language_id: LanguageIdType = Field(..., description="Language identifier from curriculum")
    major_topic_id: str = Field(..., description="e.g., 'PY_VAR_01', 'JS_FUNC_01'")
    session_type: Literal["diagnostic", "practice"] = Field(default="practice")

    @validator('user_id')
    def validate_uuid(cls, v):
        try:
            UUID(v)
        except ValueError:
            raise ValueError('Invalid UUID format for user_id')
        return v

    @validator('language_id')
    def validate_language(cls, v):
        if v not in AVAILABLE_LANGUAGES:
            raise ValueError(f'Invalid language_id: {v}. Available: {", ".join(AVAILABLE_LANGUAGES)}')
        return v

    @validator('major_topic_id')
    def validate_topic_format(cls, v):
        """Ensure format like PY_VAR_01, JS_FUNC_01, etc."""
        if not (v.count('_') >= 2 and v[-2:].isdigit()):
            raise ValueError(f'Invalid major_topic_id format: {v}')
        return v


class ExamStartResponse(BaseModel):
    """Response after starting an exam session."""
    session_id: str = Field(..., description="Session UUID for submission")
    started_at: str = Field(..., description="ISO timestamp when session started")


class ExamSubmissionPayload(BaseModel):
    """Complete exam session submission from frontend."""
    user_id: str = Field(..., description="User UUID")
    session_id: str = Field(..., description="Session UUID from /api/exam/start")
    language_id: LanguageIdType = Field(..., description="Language identifier from curriculum")
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

    @validator('language_id')
    def validate_language(cls, v):
        if v not in AVAILABLE_LANGUAGES:
            raise ValueError(f'Invalid language_id: {v}. Available: {", ".join(AVAILABLE_LANGUAGES)}')
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
    language_id: LanguageIdType = Field(..., description="Language identifier from curriculum")

    @validator('user_id')
    def validate_uuid(cls, v):
        try:
            # Normalize UUID format (ensures standard hyphenated lowercase)
            return str(UUID(v))
        except ValueError:
            raise ValueError(f'Invalid UUID format for user_id: {v}')

    @validator('language_id')
    def validate_language(cls, v):
        if v not in AVAILABLE_LANGUAGES:
            raise ValueError(f'Invalid language_id: {v}. Available: {", ".join(AVAILABLE_LANGUAGES)}')
        return v


class StateVectorResponse(BaseModel):
    """RL-ready state representation (dynamic dimensions based on curriculum)."""
    state_vector: List[float] = Field(..., min_items=1)  # Dynamic size adapts to curriculum changes
    metadata: dict = Field(..., description="Human-readable state interpretation with prerequisites, transfer potential, and error patterns")


class UserRegistrationPayload(BaseModel):
    """New user registration request."""
    email: str = Field(..., description="User email address")
    password: str = Field(..., min_length=6, description="User password (will be hashed)")
    language_id: Optional[LanguageIdType] = Field(None, description="Language identifier from curriculum (optional - set during onboarding)")
    experience_level: Optional[Literal["beginner", "intermediate", "advanced"]] = Field(
        None,
        description="Self-reported experience level for initial state priming (optional - set during onboarding)"
    )

    @validator('email')
    def validate_email(cls, v):
        if '@' not in v or '.' not in v:
            raise ValueError('Invalid email format')
        return v.lower()

    @validator('language_id')
    def validate_language(cls, v):
        if v is not None and v not in AVAILABLE_LANGUAGES:
            raise ValueError(f'Invalid language_id: {v}. Available: {", ".join(AVAILABLE_LANGUAGES)}')
        return v


class UserRegistrationResponse(BaseModel):
    """Response after successful user registration."""
    user_id: str
    message: str
    starting_topic: str = Field(..., description="Language-specific major_topic_id to start with")
    experience_level: str
    access_token: str = Field(..., description="JWT access token (30 min expiry)")
    token_type: str = Field(default="bearer", description="Token type")


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
    refresh_token: Optional[str] = Field(None, description="JWT refresh token (set as httpOnly cookie, not in response)")
    token_type: str = Field(default="bearer", description="Token type")
    user_id: str
    email: str
    last_active_language: Optional[str] = None
    is_admin: bool = Field(default=False, description="Whether user has admin privileges")


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
    language_id: LanguageIdType = Field(..., description="Language identifier from curriculum")
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

    @validator('language_id')
    def validate_language(cls, v):
        if v not in AVAILABLE_LANGUAGES:
            raise ValueError(f'Invalid language_id: {v}. Available: {", ".join(AVAILABLE_LANGUAGES)}')
        return v


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


# ==================== Admin Schemas ====================

class AdminUser(BaseModel):
    """User data structure for admin management."""
    id: str
    email: str
    name: str = Field(..., description="User display name (derived from email if not set)")
    status: str = Field(..., description="User status: active, inactive, suspended")
    language: Optional[str] = Field(None, description="Last active language")
    joinedAt: str = Field(..., description="ISO format timestamp when user joined")
    lastActive: Optional[str] = Field(None, description="ISO format timestamp of last activity")
    sessionsCompleted: int = Field(default=0, description="Total number of completed practice sessions")
    avgMastery: float = Field(default=0.0, description="Average mastery score across all topics")


class AdminUserListResponse(BaseModel):
    """Response for GET /api/admin/users endpoint."""
    success: bool = True
    users: List[AdminUser]
    total_count: int
    active_count: int
    inactive_count: int
    suspended_count: int


class AdminUserStatusUpdateRequest(BaseModel):
    """Request to update user status."""
    status: Literal["active", "inactive", "suspended"] = Field(..., description="New user status")


class AdminUserStatusUpdateResponse(BaseModel):
    """Response after updating user status."""
    success: bool = True
    message: str
    updated_user: AdminUser


class AdminUserAnalytics(BaseModel):
    """User analytics data for admin dashboard."""
    total_users: int
    active_users: int
    inactive_users: int
    suspended_users: int
    new_users_last_7_days: int
    new_users_last_30_days: int
    avg_sessions_per_user: float
    avg_mastery_across_platform: float
    most_popular_language: str
    languages_distribution: dict = Field(..., description="Language usage distribution")


