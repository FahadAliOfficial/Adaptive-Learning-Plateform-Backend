"""
User Languages Router - Manages multi-language learning paths
"""
import json
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import text, func
from typing import List, Optional, Dict
from pydantic import BaseModel, Field
from datetime import datetime

from database import get_db
from services.auth import get_current_active_user
from services.config import get_config

router = APIRouter(prefix="/api/user/languages", tags=["User Languages"])


# ==================== SCHEMAS ====================

class LanguageStats(BaseModel):
    """Statistics for a single language"""
    language_id: str
    language_name: str
    avg_mastery: float = Field(..., ge=0.0, le=1.0)
    topics_completed: int
    topics_in_progress: int
    total_topics: int
    last_practiced: Optional[str] = None
    total_sessions: int
    avg_accuracy: float = Field(..., ge=0.0, le=100.0)
    is_primary: bool
    transfer_boost: Optional[Dict] = None


class LanguagePortfolioResponse(BaseModel):
    """User's complete language learning portfolio"""
    primary_language: Optional[str] = None
    languages: List[LanguageStats]
    total_languages: int


class AddLanguageRequest(BaseModel):
    """Request to add new language to learning"""
    language_id: str
    difficulty_level: str = Field(default="beginner", pattern="^(beginner|intermediate|advanced)$")


class AddLanguageResponse(BaseModel):
    """Response after adding language"""
    message: str
    language_id: str
    language_name: str


# ==================== ENDPOINTS ====================

@router.get("", response_model=LanguagePortfolioResponse)
async def get_language_portfolio(
    current_user: dict = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Get user's complete language learning portfolio.
    
    Returns all languages the user has practiced with comprehensive stats.
    Includes transfer boost information for secondary languages.
    """
    user_id = current_user["id"]
    config = get_config()
    
    # Get user's primary language from users table
    user_result = db.execute(text("""
        SELECT primary_language, languages_learning
        FROM users
        WHERE id = :user_id
    """), {"user_id": user_id}).fetchone()
    
    primary_language = user_result[0] if user_result else None
    languages_learning = user_result[1] if user_result and user_result[1] else []
    
    # Get all languages user has practiced (from student_state)
    languages_query = text("""
        SELECT DISTINCT language_id
        FROM student_state
        WHERE user_id = :user_id
    """)
    
    practiced_languages = db.execute(languages_query, {"user_id": user_id}).fetchall()
    language_ids = [row[0] for row in practiced_languages]
    
    # Merge with languages_learning to ensure consistency
    all_languages = list(set(language_ids + languages_learning))
    
    language_stats_list = []
    
    for lang_id in all_languages:
        # Get language name from curriculum
        lang_name = _get_language_name(lang_id, config)
        
        # Calculate average mastery across all topics
        mastery_query = text("""
            SELECT AVG(mastery_score) as avg_mastery,
                   COUNT(DISTINCT CASE WHEN mastery_score >= 0.8 THEN mapping_id END) as topics_completed,
                   COUNT(DISTINCT CASE WHEN mastery_score > 0 AND mastery_score < 0.8 THEN mapping_id END) as topics_in_progress,
                   MAX(last_practiced_at) as last_practiced
            FROM student_state
            WHERE user_id = :user_id AND language_id = :lang_id
        """)
        
        mastery_result = db.execute(mastery_query, {
            "user_id": user_id,
            "lang_id": lang_id
        }).fetchone()
        
        avg_mastery = mastery_result[0] if mastery_result[0] else 0.0
        topics_completed = mastery_result[1] if mastery_result[1] else 0
        topics_in_progress = mastery_result[2] if mastery_result[2] else 0
        last_practiced = mastery_result[3].isoformat() if mastery_result[3] else None
        
        # Get total topics for this language from curriculum
        total_topics = _get_total_topics_for_language(lang_id, config)
        
        # Get session statistics (only count 'exam' type sessions for learning metrics)
        session_query = text("""
            SELECT COUNT(*) as total_sessions,
                   AVG(overall_score) as avg_accuracy
            FROM exam_sessions
            WHERE user_id = :user_id 
              AND language_id = :lang_id
              AND session_type = 'exam'
              AND session_status = 'completed'
              AND overall_score IS NOT NULL
        """)
        
        session_result = db.execute(session_query, {
            "user_id": user_id,
            "lang_id": lang_id
        }).fetchone()
        
        total_sessions = session_result[0] if session_result[0] else 0
        # Convert accuracy to percentage (0-100 scale)
        avg_accuracy = (session_result[1] * 100) if session_result[1] else 0.0
        
        # Calculate transfer boost if this is not primary language
        transfer_boost = None
        if primary_language and lang_id != primary_language:
            transfer_boost = _calculate_transfer_boost(
                user_id, primary_language, lang_id, db, config
            )
        
        language_stats_list.append(LanguageStats(
            language_id=lang_id,
            language_name=lang_name,
            avg_mastery=round(avg_mastery, 2),
            topics_completed=topics_completed,
            topics_in_progress=topics_in_progress,
            total_topics=total_topics,
            last_practiced=last_practiced,
            total_sessions=total_sessions,
            avg_accuracy=round(avg_accuracy, 1),
            is_primary=(lang_id == primary_language),
            transfer_boost=transfer_boost
        ))
    
    # Sort: primary first, then by avg_mastery descending
    language_stats_list.sort(
        key=lambda x: (not x.is_primary, -x.avg_mastery)
    )
    
    return LanguagePortfolioResponse(
        primary_language=primary_language,
        languages=language_stats_list,
        total_languages=len(language_stats_list)
    )


@router.post("", response_model=AddLanguageResponse)
async def add_language_to_learning(
    payload: AddLanguageRequest,
    current_user: dict = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Add a new language to user's learning portfolio.
    
    This creates a secondary language learning path.
    The language will be added to languages_learning array.
    """
    user_id = current_user["id"]
    language_id = payload.language_id
    config = get_config()
    
    # Validate language exists in curriculum
    language_name = _get_language_name(language_id, config)
    if not language_name:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Language '{language_id}' not found in curriculum"
        )
    
    # Get current languages_learning
    user_result = db.execute(text("""
        SELECT languages_learning, primary_language
        FROM users
        WHERE id = :user_id
    """), {"user_id": user_id}).fetchone()
    
    current_languages = user_result[0] if user_result and user_result[0] else []
    primary_language = user_result[1] if user_result else None
    
    # Check if language already added
    if language_id in current_languages:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Language '{language_name}' is already in your learning portfolio"
        )
    
    # Limit to maximum 5 languages
    if len(current_languages) >= 5:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Maximum 5 languages allowed. Remove a language before adding new one."
        )
    
    # Add language to array
    new_languages = list(set(current_languages + [language_id]))
    serialized = json.dumps(new_languages)
    
    # If this is the first language, set it as primary
    set_as_primary = primary_language is None
    
    if set_as_primary:
        db.execute(text("""
            UPDATE users
            SET languages_learning = CAST(:languages AS jsonb),
                primary_language = :lang_id,
                last_active_language = :lang_id
            WHERE id = :user_id
        """), {
            "languages": serialized,
            "lang_id": language_id,
            "user_id": user_id
        })
    else:
        db.execute(text("""
            UPDATE users
            SET languages_learning = CAST(:languages AS jsonb)
            WHERE id = :user_id
        """), {
            "languages": serialized,
            "user_id": user_id
        })
    
    # Seed initial student state based on difficulty level
    difficulty_level = payload.difficulty_level or "beginner"
    exp_config = config.get_experience_config(difficulty_level)
    initial_mastery = exp_config.get('initial_mastery_estimate', 0.0)
    assumed_mastered = exp_config.get('assumed_mastered', [])
    
    for mapping_id in assumed_mastered:
        db.execute(text("""
            INSERT INTO student_state 
                (user_id, mapping_id, language_id, mastery_score, fluency_score, confidence_score, last_practiced_at, last_updated)
            VALUES 
                (:user_id, :mapping_id, :language_id, :mastery, :fluency, :confidence, NOW(), NOW())
            ON CONFLICT (user_id, mapping_id, language_id) 
            DO NOTHING
        """), {
            "user_id": user_id,
            "mapping_id": mapping_id,
            "language_id": language_id,
            "mastery": initial_mastery,
            "fluency": 1.2,
            "confidence": 0.5
        })
    
    db.commit()
    
    message = f"Added {language_name} as {'primary' if set_as_primary else 'secondary'} language"
    
    return AddLanguageResponse(
        message=message,
        language_id=language_id,
        language_name=language_name
    )


# ==================== HELPER FUNCTIONS ====================

def _get_language_name(language_id: str, config) -> str:
    """Get human-readable language name from config"""
    curriculum = config.curriculum
    for lang in curriculum:
        if lang["language_id"] == language_id:
            return lang["name"]
    return language_id  # Fallback to ID


def _get_total_topics_for_language(language_id: str, config) -> int:
    """Get total number of topics/concepts for a language"""
    curriculum = config.curriculum
    for lang in curriculum:
        if lang["language_id"] == language_id:
            return len(lang["roadmap"])
    return 8  # Default to 8 universal concepts


def _calculate_transfer_boost(
    user_id: str,
    source_lang: str,
    target_lang: str,
    db: Session,
    config
) -> Optional[Dict]:
    """
    Calculate cross-language transfer boost from primary to secondary language.
    
    Returns transfer information if applicable.
    """
    # Get transfer configuration
    transfer_map = config.transition_map.get("cross_language_transfer", [])
    
    # Find matching transfer rule
    transfer_rule = None
    for rule in transfer_map:
        if (rule["source_language_id"] == source_lang and 
            rule["target_language_id"] == target_lang):
            transfer_rule = rule
            break
    
    if not transfer_rule:
        return None
    
    # Get source language average mastery
    source_mastery_result = db.execute(text("""
        SELECT AVG(mastery_score) as avg_mastery
        FROM student_state
        WHERE user_id = :user_id AND language_id = :lang_id
    """), {
        "user_id": user_id,
        "lang_id": source_lang
    }).fetchone()
    
    source_avg_mastery = source_mastery_result[0] if source_mastery_result[0] else 0.0
    
    # Only show transfer if source mastery is significant
    if source_avg_mastery < 0.3:
        return None
    
    return {
        "from_language": source_lang,
        "from_language_name": _get_language_name(source_lang, config),
        "source_mastery": round(source_avg_mastery, 2),
        "acceleration_factor": transfer_rule["logic_acceleration"],
        "estimated_boost": round(source_avg_mastery * transfer_rule["logic_acceleration"] * 0.8, 2)
    }
