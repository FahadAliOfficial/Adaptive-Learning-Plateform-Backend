"""
Dashboard Router - Unified endpoints for dashboard data
Provides comprehensive student progress information including mastery,
decay alerts, RL recommendations, transfer boosts, synergy bonuses, and session history.
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy import text, and_, desc
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Optional, Any
import numpy as np
import json

from database import get_db
from services.auth import get_current_active_user
from services.rl.rl_service import get_rl_service
from services.state_vector_service import StateVectorGenerator
from services.schemas import StateVectorRequest, RecommendationRequest
from services.config import get_config, CurriculumConfig

router = APIRouter(tags=["Dashboard"])


# ==================== Response Schemas ====================

from pydantic import BaseModel, Field

class MasteryData(BaseModel):
    """Individual topic mastery data."""
    mapping_id: str
    name: str
    mastery: float
    decayed_mastery: float
    confidence: float
    fluency: float
    last_practiced: Optional[str]  # ISO timestamp
    days_since_practice: int


class DecayAlert(BaseModel):
    """Knowledge decay alert for a topic."""
    concept_id: str
    concept_name: str
    current_mastery: float
    original_mastery: float
    days_passed: int


class RecommendedTopic(BaseModel):
    """RL recommendation adapted to frontend format."""
    concept_id: str
    concept_name: str
    sub_topic: str
    target_difficulty: float
    estimated_time_minutes: int
    reason: str
    prerequisite_met: bool


class RecentSession(BaseModel):
    """Recent exam session summary."""
    id: str
    timestamp: str
    concept_id: str
    concept_name: str
    sub_topic: Optional[str]
    score: float
    difficulty: float
    mastery_gain: float
    questions_answered: int


class DashboardSummaryResponse(BaseModel):
    """Comprehensive dashboard data."""
    mastery_data: List[MasteryData]
    decay_alerts: List[DecayAlert]
    recommendation: Optional[RecommendedTopic]
    recent_sessions: List[RecentSession]


class TransferBoost(BaseModel):
    """Cross-language transfer boost."""
    source_language: str
    source_concept: str
    target_language: str
    target_concept: str
    source_mastery: float
    boost_amount: float
    transfer_coefficient: float
    logic_boost: float


class SynergyBonus(BaseModel):
    """Within-language synergy bonus."""
    from_concept: str
    to_concept: str
    bonus_amount: float
    reinforcement_weight: float
    bidirectional: bool
    session_id: Optional[str]
    applied_at: Optional[str]


# ==================== Helper Functions ====================

def _calculate_time_decay(mastery: float, days_inactive: int) -> float:
    """Apply exponential decay to mastery score."""
    decay_rate = 0.02  # Matches StateVectorService
    return float(mastery * np.exp(-decay_rate * days_inactive))


def _map_rl_to_recommended_topic(
    rl_response: dict,
    config: CurriculumConfig,
    db: Session
) -> RecommendedTopic:
    """
    Convert RL recommendation response to RecommendedTopic format.
    Resolves topic names and extracts metadata.
    """
    mapping_id = rl_response['mapping_id']
    major_topic_id = rl_response['major_topic_id']
    difficulty = rl_response['difficulty']
    metadata = rl_response.get('metadata', {})
    
    # Get topic name from curriculum
    topic_data = config.mapping_to_topics.get(mapping_id, {})
    # Get name from any language (they all have the same mapping name)
    topic_name = next((lang_data['name'] for lang_data in topic_data.values() if 'name' in lang_data), mapping_id)
    
    # Extract sub_topic from major_topic_id (e.g., "PY_FUNC_01" → "PY_FUNC")
    sub_topic = major_topic_id.rsplit('_', 1)[0] if '_' in major_topic_id else major_topic_id
    
    # Estimate time based on difficulty
    estimated_time = int(15 + (difficulty * 15))  # 15-30 minutes range
    
    # Generate reason from metadata
    prereq_check = metadata.get('prerequisite_check', {})
    prerequisite_met = prereq_check.get('passed', True)
    
    if prerequisite_met:
        reason = f"AI-recommended based on your current mastery profile. Optimized difficulty for your learning pace."
    else:
        reason = f"Recommended with caution: some prerequisites may need review."
    
    return RecommendedTopic(
        concept_id=mapping_id,
        concept_name=topic_name,
        sub_topic=sub_topic,
        target_difficulty=difficulty,
        estimated_time_minutes=estimated_time,
        reason=reason,
        prerequisite_met=prerequisite_met
    )


def _check_topic_accessibility(
    mapping_id: str,
    mastery_dict: Dict[str, float],
    config: CurriculumConfig,
    language_id: str
) -> bool:
    """
    Check if a topic is accessible based on prerequisites and soft gates.
    Replicates logic from user_languages_router.py
    
    Returns:
        True if accessible (prerequisites met or already practiced)
    """
    # If user has practiced this topic, it's always accessible
    if mapping_id in mastery_dict:
        return True
    
    # Check soft gate requirements (stricter gates for critical concepts)
    gate = config.get_soft_gate(mapping_id)
    
    if gate:
        # Use soft gate if defined (for FUNC, COLL, OOP)
        prereq_mappings = gate.get('prerequisite_mappings', [])
        min_score = gate.get('minimum_allowable_score', 0.6)
        
        for prereq_id in prereq_mappings:
            current_mastery = mastery_dict.get(prereq_id, 0.0)
            if current_mastery < min_score:
                return False  # Prerequisite not met
        
        return True  # All soft gate prerequisites met
    
    # No soft gate: check sequential prerequisites from curriculum
    # Find the topic in the curriculum to get its prerequisites
    curriculum = config.curriculum
    language_curriculum = None
    for lang in curriculum:
        if lang["language_id"] == language_id:
            language_curriculum = lang
            break
    
    if not language_curriculum:
        return True  # Can't validate without curriculum
    
    # Find topic in roadmap
    topic_prerequisites = []
    for topic in language_curriculum["roadmap"]:
        if topic["mapping_id"] == mapping_id:
            topic_prerequisites = topic.get("prerequisites", [])
            break
    
    if not topic_prerequisites:
        # No prerequisites = first topic, always accessible
        return True
    
    # Check if all sequential prerequisites are practiced with minimum mastery
    # Use lower threshold (0.3) for sequential unlocking vs soft gates (0.6)
    for prereq_id in topic_prerequisites:
        if prereq_id not in mastery_dict or mastery_dict[prereq_id] < 0.3:
            return False  # Sequential prerequisite not met
    
    return True  # All prerequisites met


def _get_first_accessible_incomplete(
    mastery_dict: Dict[str, float],
    language_id: str,
    config: CurriculumConfig
) -> Optional[Dict]:
    """
    Get the first accessible incomplete topic as fallback.
    Calculates appropriate difficulty based on current mastery.
    
    Returns:
        RL response dict or None
    """
    curriculum = config.curriculum
    language_curriculum = None
    for lang in curriculum:
        if lang["language_id"] == language_id:
            language_curriculum = lang
            break
    
    if not language_curriculum:
        return None
    
    # Find first incomplete accessible topic
    for topic in language_curriculum["roadmap"]:
        mapping_id = topic["mapping_id"]
        mastery = mastery_dict.get(mapping_id, 0.0)
        
        # Check if incomplete (< 75% mastery)
        if mastery < 0.75:
            # Check if accessible
            is_accessible = _check_topic_accessibility(
                mapping_id, mastery_dict, config, language_id
            )
            
            if is_accessible:
                # Calculate appropriate difficulty based on current mastery
                # Low mastery (< 30%): Easy difficulty (0.3-0.4) to build foundation
                # Medium mastery (30-60%): Medium difficulty (0.5-0.6) to practice
                # High mastery (60-75%): Hard difficulty (0.8) to reach mastery threshold
                if mastery < 0.3:
                    difficulty = 0.35  # Easy - focus on building confidence
                elif mastery < 0.6:
                    difficulty = 0.55  # Medium - practice and reinforce
                else:
                    difficulty = 0.75  # Hard - challenge to push towards mastery
                
                # Found first accessible incomplete topic
                major_topic_id = config.get_major_topic_id(language_id, mapping_id)
                
                return {
                    'mapping_id': mapping_id,
                    'major_topic_id': major_topic_id,
                    'difficulty': difficulty,
                    'action_id': -1,  # Fallback indicator
                    'strategy_used': 'accessibility_fallback',
                    'confidence': None,
                    'metadata': {
                        'prerequisite_check': {'passed': True, 'violations': []},
                        'language_id': language_id,
                        'fallback_reason': 'rl_suggested_locked_topic',
                        'original_mastery': mastery,
                        'calculated_difficulty': difficulty
                    }
                }
    
    return None  # No accessible incomplete topics found


# ==================== Endpoints ====================

@router.get("/api/dashboard/summary", response_model=DashboardSummaryResponse)
async def get_dashboard_summary(
    language_id: str = Query(..., description="Target language"),
    current_user: dict = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Get comprehensive dashboard data in one request.
    Includes mastery, decay alerts, RL recommendation, and recent sessions.
    """
    user_id = current_user["id"]
    config = get_config()
    
    # 1. Get state vector and mastery data
    state_gen = StateVectorGenerator(db)
    state_vector_obj = None
    try:
        state_vector_obj = state_gen.generate_vector(
            StateVectorRequest(user_id=user_id, language_id=language_id)
        )
        mastery_breakdown = state_vector_obj.metadata.get('mastery_breakdown', [])
    except Exception as e:
        # User may not have any data yet
        mastery_breakdown = []
        state_vector_obj = None
    
    # 2. Build mastery data with decay
    mastery_data_list = []
    decay_alerts_list = []
    
    for topic in mastery_breakdown:
        mapping_id = topic['mapping_id']
        original_mastery = topic['mastery']
        days_inactive = topic['days_since_practice']
        
        # Apply decay
        decayed_mastery = _calculate_time_decay(original_mastery, days_inactive)
        
        # Get topic name
        topic_data = config.mapping_to_topics.get(mapping_id, {})
        topic_name = next((lang_data['name'] for lang_data in topic_data.values() if 'name' in lang_data), mapping_id)
        
        mastery_data_list.append(MasteryData(
            mapping_id=mapping_id,
            name=topic_name,
            mastery=original_mastery,
            decayed_mastery=decayed_mastery,
            confidence=topic.get('confidence', 0.0),
            fluency=topic.get('fluency', 0.0),
            last_practiced=topic.get('last_practiced'),
            days_since_practice=days_inactive
        ))
        
        # Check for decay alert: >15% decay AND >3 days inactive
        if (original_mastery - decayed_mastery) / (original_mastery + 0.01) > 0.15 and days_inactive > 3:
            decay_alerts_list.append(DecayAlert(
                concept_id=mapping_id,
                concept_name=topic_name,
                current_mastery=decayed_mastery,
                original_mastery=original_mastery,
                days_passed=days_inactive
            ))
    
    # 3. Get RL recommendation
    recommendation = None
    try:
        # Only get recommendation if we have state vector data
        if state_vector_obj and len(mastery_breakdown) > 0:
            rl_service = get_rl_service()
            state_vector = np.array(state_vector_obj.state_vector)  # Convert to numpy array
            mastery_dict = {t['mapping_id']: t['mastery'] for t in mastery_breakdown}
            
            rl_response = rl_service.get_recommendation(
                state_vector=state_vector,  # Pass as first positional argument
                mastery_dict=mastery_dict,
                language_id=language_id,
                strategy="dqn",  # Use DQN for curriculum-safe recommendations
                deterministic=True
            )
            
            # NEW: Check if recommended topic is accessible (not locked)
            recommended_mapping_id = rl_response.get('mapping_id')
            is_accessible = _check_topic_accessibility(
                recommended_mapping_id,
                mastery_dict,
                config,
                language_id
            )
            
            if not is_accessible:
                # RL suggested a locked topic - fall back to first accessible incomplete
                print(f"⚠️ RL suggested locked topic {recommended_mapping_id}, falling back to first accessible")
                fallback_response = _get_first_accessible_incomplete(
                    mastery_dict, language_id, config
                )
                
                if fallback_response:
                    rl_response = fallback_response
                else:
                    # No accessible topics at all - skip recommendation
                    print("⚠️ No accessible topics found - skipping recommendation")
                    rl_response = None
            
            if rl_response:
                recommendation = _map_rl_to_recommended_topic(rl_response, config, db)
        else:
            print("⚠️ Skipping RL recommendation - insufficient mastery data")
    except Exception as e:
        # RL may fail if user has no data or model not loaded
        print(f"⚠️ RL recommendation failed: {e}")
        recommendation = None
    
    # 4. Get recent sessions
    recent_sessions_list = []
    try:
        recent_sessions_query = text("""
            SELECT 
                s.id, s.started_at, s.major_topic_id,
                s.overall_score, s.difficulty_assigned,
                COUNT(uqh.id) as question_count
            FROM exam_sessions s
            LEFT JOIN user_question_history uqh ON uqh.session_id = s.id
            WHERE s.user_id = :user_id 
              AND s.language_id = :language_id
              AND s.session_status = 'completed'
            GROUP BY s.id
            ORDER BY s.started_at DESC
            LIMIT 5
        """)
        
        sessions = db.execute(recent_sessions_query, {
            "user_id": user_id,
            "language_id": language_id
        }).fetchall()
        
        for session in sessions:
            # Get mapping_id from major_topic_id
            major_topic_id = session.major_topic_id
            mapping_id = config.get_mapping_id(language_id, major_topic_id)
            topic_data = config.mapping_to_topics.get(mapping_id, {})
            topic_name = next((lang_data['name'] for lang_data in topic_data.values() if 'name' in lang_data), mapping_id)
            
            recent_sessions_list.append(RecentSession(
                id=session.id,
                timestamp=session.started_at.isoformat() if session.started_at else None,
                concept_id=mapping_id,
                concept_name=topic_name,
                sub_topic=major_topic_id,
                score=float(session.overall_score) if session.overall_score else 0.0,
                difficulty=float(session.difficulty_assigned) if session.difficulty_assigned else 0.5,
                mastery_gain=0.0,  # TODO: Calculate from student_state diff
                questions_answered=session.question_count
            ))
    except Exception as e:
        print(f"⚠️ Failed to fetch recent sessions: {e}")
    
    return DashboardSummaryResponse(
        mastery_data=mastery_data_list,
        decay_alerts=decay_alerts_list,
        recommendation=recommendation,
        recent_sessions=recent_sessions_list
    )


@router.get("/api/user/mastery/{language_id}", response_model=List[MasteryData])
async def get_user_mastery(
    language_id: str,
    current_user: dict = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Get simplified mastery data for a specific language.
    Used by mastery heatmap component.
    """
    user_id = current_user["id"]
    config = get_config()
    
    # Query student_state
    query = text("""
        SELECT 
            mapping_id,
            mastery_score,
            confidence_score,
            fluency_score,
            last_practiced_at
        FROM student_state
        WHERE user_id = :user_id AND language_id = :language_id
    """)
    
    results = db.execute(query, {
        "user_id": user_id,
        "language_id": language_id
    }).fetchall()
    
    mastery_list = []
    now = datetime.now(timezone.utc)
    
    for row in results:
        # Calculate days since practice
        if row.last_practiced_at:
            days_inactive = (now - row.last_practiced_at).days
        else:
            days_inactive = 999
        
        # Apply decay
        decayed = _calculate_time_decay(row.mastery_score, days_inactive)
        
        # Get topic name
        topic_data = config.mapping_to_topics.get(row.mapping_id, {})
        topic_name = next((lang_data['name'] for lang_data in topic_data.values() if 'name' in lang_data), row.mapping_id)
        
        mastery_list.append(MasteryData(
            mapping_id=row.mapping_id,
            name=topic_name,
            mastery=float(row.mastery_score),
            decayed_mastery=float(decayed),
            confidence=float(row.confidence_score),
            fluency=float(row.fluency_score),
            last_practiced=row.last_practiced_at.isoformat() if row.last_practiced_at else None,
            days_since_practice=days_inactive
        ))
    
    return mastery_list


@router.get("/api/transfer/active-boosts", response_model=List[TransferBoost])
async def get_active_transfer_boosts(
    language_id: str = Query(..., description="Target language to show boosts for"),
    current_user: dict = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Get cross-language transfer boosts for the current user.
    Shows how mastery in other languages boosts learning in the target language.
    """
    user_id = current_user["id"]
    config = get_config()
    
    # Get user's languages
    user_query = text("""
        SELECT primary_language, languages_learning
        FROM users
        WHERE id = :user_id
    """)
    user_data = db.execute(user_query, {"user_id": user_id}).fetchone()
    
    if not user_data or not user_data.languages_learning:
        return []
    
    languages_learning = json.loads(user_data.languages_learning) if isinstance(user_data.languages_learning, str) else user_data.languages_learning
    
    # Get transfer config from transition_map
    transfer_config = config.transition_map.get('cross_language_transfer', {})
    
    boosts = []
    
    # For each language the user knows (excluding target)
    for source_lang in languages_learning:
        if source_lang == language_id:
            continue
        
        # Query mastery in source language
        source_query = text("""
            SELECT mapping_id, mastery_score
            FROM student_state
            WHERE user_id = :user_id AND language_id = :language_id AND mastery_score > 0.5
        """)
        
        source_masteries = db.execute(source_query, {
            "user_id": user_id,
            "language_id": source_lang
        }).fetchall()
        
        for source_row in source_masteries:
            mapping_id = source_row.mapping_id
            source_mastery = source_row.mastery_score
            
            # Get transfer coefficient for this mapping
            logic_acceleration = transfer_config.get(mapping_id, {}).get('logic_acceleration', 0.7)
            
            # Calculate boost: source_mastery × logic_acceleration × 0.8
            boost_amount = float(source_mastery * logic_acceleration * 0.8)
            
            if boost_amount > 0.05:  # Only show meaningful boosts
                topic_data = config.mapping_to_topics.get(mapping_id, {})
                topic_name = next((lang_data['name'] for lang_data in topic_data.values() if 'name' in lang_data), mapping_id)
                
                boosts.append(TransferBoost(
                    source_language=source_lang,
                    source_concept=mapping_id,
                    target_language=language_id,
                    target_concept=mapping_id,  # Same universal mapping
                    source_mastery=float(source_mastery),
                    boost_amount=boost_amount,
                    transfer_coefficient=logic_acceleration,
                    logic_boost=float(source_mastery * logic_acceleration)
                ))
    
    return boosts


@router.get("/api/synergy/recent-bonuses", response_model=List[SynergyBonus])
async def get_recent_synergy_bonuses(
    language_id: str = Query(..., description="Language to show synergy for"),
    days: int = Query(7, description="Number of days to look back"),
    current_user: dict = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Get recent synergy bonuses applied in the last N days.
    Synergy occurs when mastering one topic reinforces related topics.
    """
    user_id = current_user["id"]
    config = get_config()
    
    # Load concept interdependencies from config file
    from pathlib import Path
    interdep_path = Path(__file__).parent.parent / 'core' / 'concept_interdependencies_config.json'
    try:
        with open(interdep_path, 'r', encoding='utf-8') as f:
            interdep_data = json.load(f)
        interdependencies_list = interdep_data.get('concept_interdependencies', [])
        # Build lookup: {mapping_id: {related_mapping_id: coefficient, ...}}
        interdependencies = {}
        for dep in interdependencies_list:
            a, b = dep['mapping_a'], dep['mapping_b']
            coef = dep['reinforcement_coefficient']
            if a not in interdependencies:
                interdependencies[a] = {}
            if b not in interdependencies:
                interdependencies[b] = {}
            interdependencies[a][b] = coef
            interdependencies[b][a] = coef  # Bidirectional
    except Exception as e:
        print(f"⚠️ Failed to load concept interdependencies: {e}")
        interdependencies = {}
    
    # Query recent high-scoring sessions (synergy trigger threshold = 70%)
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)
    
    query = text("""
        SELECT 
            s.id as session_id,
            s.major_topic_id,
            s.overall_score,
            s.completed_at
        FROM exam_sessions s
        WHERE s.user_id = :user_id
          AND s.language_id = :language_id
          AND s.session_status = 'completed'
          AND s.overall_score >= 0.7
          AND s.completed_at >= :cutoff_date
        ORDER BY s.completed_at DESC
        LIMIT 10
    """)
    
    sessions = db.execute(query, {
        "user_id": user_id,
        "language_id": language_id,
        "cutoff_date": cutoff_date
    }).fetchall()
    
    synergies = []
    
    for session in sessions:
        major_topic_id = session.major_topic_id
        mapping_id = config.get_mapping_id(language_id, major_topic_id)
        
        # Find synergy pairs for this mapping
        if mapping_id in interdependencies:
            for related_mapping, strength in interdependencies[mapping_id].items():
                # Calculate bonus: strength × 0.1 (matches GradingService formula)
                bonus = float(session.overall_score * strength * 0.1)
                
                topic_data_from = config.mapping_to_topics.get(mapping_id, {})
                from_name = next((lang_data['name'] for lang_data in topic_data_from.values() if 'name' in lang_data), mapping_id)
                topic_data_to = config.mapping_to_topics.get(related_mapping, {})
                to_name = next((lang_data['name'] for lang_data in topic_data_to.values() if 'name' in lang_data), related_mapping)
                
                # Check if bidirectional
                bidirectional = related_mapping in interdependencies and mapping_id in interdependencies[related_mapping]
                
                synergies.append(SynergyBonus(
                    from_concept=mapping_id,
                    to_concept=related_mapping,
                    bonus_amount=bonus,
                    reinforcement_weight=strength,
                    bidirectional=bidirectional,
                    session_id=session.session_id,
                    applied_at=session.completed_at.isoformat() if session.completed_at else None
                ))
    
    return synergies
