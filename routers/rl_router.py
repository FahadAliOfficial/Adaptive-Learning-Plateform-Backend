"""
RL Recommendation Router - Curriculum decision endpoints using trained RL models
Provides POST /api/rl/recommend with prerequisite validation and fallback logic.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime, timezone
import uuid

from database import get_db
from services.rl.rl_service import get_rl_service
from services.state_vector_service import StateVectorGenerator
from services.schemas import (
    RecommendationRequest,
    RecommendationResponse,
    StateVectorRequest,
    HealthStatusResponse
)
from services.auth import get_current_active_user


router = APIRouter(prefix="/api/rl", tags=["Reinforcement Learning"])


@router.post("/recommend", response_model=RecommendationResponse)
async def get_recommendation(
    request: RecommendationRequest,
    current_user: dict = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Get RL-powered curriculum recommendation with prerequisite validation.
    
    **Workflow:**
    1. Generate 38D state vector from database
    2. Use RL model (PPO/DQN/A2C/Ensemble) to predict next topic
    3. Validate prerequisites from transition_map.json
    4. Fallback to baseline if prerequisites violated
    5. Convert universal mapping_id to language-specific major_topic_id
    
    **Strategies:**
    - `ppo`: Proximal Policy Optimization (recommended for production)
    - `dqn`: Deep Q-Network (value-based alternative)
    - `a2c`: Advantage Actor-Critic (policy gradient alternative)
    - `ensemble`: Majority voting across all 3 models
    - `baseline`: Rule-based fallback (lowest mastery with prerequisites met)
    
    **Returns:** Recommendation with mapping_id, major_topic_id, difficulty, metadata
    """
    
    # Verify user can only get recommendations for themselves
    if request.user_id != current_user["id"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot get recommendations for other users"
        )
    
    try:
        # 1. Generate state vector from database
        state_gen = StateVectorGenerator(db)
        state_vector_obj = state_gen.generate_vector(
            StateVectorRequest(
                user_id=request.user_id,
                language_id=request.language_id
            )
        )
        
        # Extract state vector and mastery dict
        state_vector = state_vector_obj.state_vector  # List[float] 38D
        
        # Extract mastery mapping from metadata
        mastery_dict = {}
        for topic_data in state_vector_obj.metadata.get('mastery_breakdown', []):
            mastery_dict[topic_data['mapping_id']] = topic_data['mastery']
        
        # 2. Get RL service and generate recommendation
        rl_service = get_rl_service()
        
        import numpy as np
        recommendation = rl_service.get_recommendation(
            state_vector=np.array(state_vector, dtype=np.float32),
            mastery_dict=mastery_dict,
            language_id=request.language_id,
            strategy=request.strategy,
            deterministic=request.deterministic
        )
        
        # 3. Log recommendation to database for history tracking
        recommendation_id = str(uuid.uuid4())
        try:
            log_query = text("""
                INSERT INTO rl_recommendation_history (
                    id, user_id, language_id, strategy, mapping_id, major_topic_id,
                    difficulty, action_id, confidence, prerequisite_check_passed, 
                    metadata, created_at
                ) VALUES (
                    :id, :user_id, :language_id, :strategy, :mapping_id, :major_topic_id,
                    :difficulty, :action_id, :confidence, :prereq_passed,
                    :metadata, :created_at
                )
            """)
            
            import json
            db.execute(log_query, {
                'id': recommendation_id,
                'user_id': request.user_id,
                'language_id': request.language_id,
                'strategy': recommendation['strategy_used'],
                'mapping_id': recommendation['mapping_id'],
                'major_topic_id': recommendation['major_topic_id'],
                'difficulty': recommendation['difficulty'],
                'action_id': recommendation['action_id'],
                'confidence': recommendation['confidence'],
                'prereq_passed': recommendation['metadata']['prerequisite_check']['passed'],
                'metadata': json.dumps(recommendation['metadata']),
                'created_at': datetime.now(timezone.utc)
            })
            db.commit()
        except Exception as log_error:
            # Don't fail recommendation if logging fails
            print(f"⚠️ Failed to log recommendation: {log_error}")
            db.rollback()
        
        # 4. Return structured response
        response = RecommendationResponse(
            mapping_id=recommendation['mapping_id'],
            major_topic_id=recommendation['major_topic_id'],
            difficulty=recommendation['difficulty'],
            action_id=recommendation['action_id'],
            strategy_used=recommendation['strategy_used'],
            confidence=recommendation['confidence'],
            metadata=recommendation['metadata']
        )
        
        # Add recommendation_id to metadata for client tracking
        response.metadata['recommendation_id'] = recommendation_id
        
        return response
    
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Recommendation failed: {str(e)}"
        )


@router.get("/health", response_model=HealthStatusResponse)
async def get_health_status():
    """
    Check RL service health status and available models.
    
    **Returns:**
    - Service status (healthy/degraded)
    - Models loaded status (ppo, dqn, a2c)
    - Available strategies based on loaded models
    - Environment initialization status
    """
    
    rl_service = get_rl_service()
    health = rl_service.get_health_status()
    
    return HealthStatusResponse(
        service=health['service'],
        status=health['status'],
        models_loaded=health['models_loaded'],
        environment_ready=health['environment_ready'],
        available_strategies=health['available_strategies']
    )


@router.get("/strategies")
async def list_available_strategies():
    """
    List currently available RL strategies.
    
    **Returns:** Dict with available strategies and their descriptions
    """
    
    rl_service = get_rl_service()
    available = rl_service._get_available_strategies()
    
    strategy_info = {
        'ppo': {
            'name': 'Proximal Policy Optimization',
            'type': 'policy_gradient',
            'description': 'Recommended for production - stable and sample efficient',
            'available': 'ppo' in available
        },
        'dqn': {
            'name': 'Deep Q-Network',
            'type': 'value_based',
            'description': 'Value-based alternative with experience replay',
            'available': 'dqn' in available
        },
        'a2c': {
            'name': 'Advantage Actor-Critic',
            'type': 'policy_gradient',
            'description': 'On-policy actor-critic method',
            'available': 'a2c' in available
        },
        'ensemble': {
            'name': 'Ensemble (Majority Vote)',
            'type': 'ensemble',
            'description': 'Combines all available models via majority voting',
            'available': 'ensemble' in available
        },
        'baseline': {
            'name': 'Rule-Based Baseline',
            'type': 'rule_based',
            'description': 'Fallback strategy - lowest mastery with prerequisites met',
            'available': True  # Always available
        }
    }
    
    return {
        'available_strategies': available,
        'strategy_details': strategy_info
    }


@router.get("/history/{user_id}")
async def get_recommendation_history(
    user_id: str,
    limit: int = 10,
    current_user: dict = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Get recommendation history for a user.
    
    **Returns:** List of past recommendations with follow-up status
    """
    
    # Verify user can only access their own history (or admin)
    if current_user['id'] != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot access other user's recommendation history"
        )
    
    query = text("""
        SELECT 
            id, strategy, mapping_id, major_topic_id, difficulty,
            confidence, prerequisite_check_passed, followed_up,
            created_at, followed_up_at
        FROM rl_recommendation_history
        WHERE user_id = :user_id
        ORDER BY created_at DESC
        LIMIT :limit
    """)
    
    result = db.execute(query, {'user_id': user_id, 'limit': limit})
    
    history = []
    for row in result:
        history.append({
            'recommendation_id': row[0],
            'strategy': row[1],
            'mapping_id': row[2],
            'major_topic_id': row[3],
            'difficulty': row[4],
            'confidence': row[5],
            'prerequisite_check_passed': bool(row[6]),
            'followed_up': bool(row[7]),
            'recommended_at': row[8].isoformat() if row[8] else None,
            'followed_up_at': row[9].isoformat() if row[9] else None
        })
    
    return {
        'user_id': user_id,
        'total_recommendations': len(history),
        'history': history
    }
