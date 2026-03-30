"""
RL Model Service - Singleton for managing trained RL models
Provides curriculum recommendation using PPO, DQN, A2C agents with prerequisite validation.
"""
from typing import Dict, Optional, Tuple, List
from functools import lru_cache
import numpy as np
from sqlalchemy.orm import Session

from services.rl.ppo_agent import PPOAgent
from services.rl.dqn_agent import DQNAgent
from services.rl.a2c_agent import A2CAgent
from services.rl.adaptive_learning_env import AdaptiveLearningEnv
from services.rl.student_simulator import StudentSimulator
from services.config import get_config


class RLModelService:
    """
    Singleton service for RL model management and inference.
    Loads trained models once at startup and provides recommendation API.
    """
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
            
        self.config = get_config()
        self.models: Dict[str, Optional[object]] = {
            'ppo': None,
            'dqn': None,
            'a2c': None
        }
        self.env: Optional[AdaptiveLearningEnv] = None
        self.models_loaded = False
        self._initialized = True
    
    def load_models(self, device: str = "auto") -> Dict[str, bool]:
        """
        Load all trained RL models at application startup.
        
        Args:
            device: Device for model inference ("cpu", "cuda", or "auto")
        
        Returns:
            Dict mapping model names to load success status
        """
        if self.models_loaded:
            print("⚠️ Models already loaded, skipping re-initialization")
            return {k: v is not None for k, v in self.models.items()}
        
        # Initialize environment (required for model loading)
        print("🔧 Initializing RL environment...")
        self.env = AdaptiveLearningEnv(StudentSimulator(seed=42))
        
        load_status = {}
        model_configs = [
            ('ppo', PPOAgent, './models/ppo/best/best_model'),
            ('dqn', DQNAgent, './models/dqn/best/best_model'),
            ('a2c', A2CAgent, './models/a2c/best/best_model')
        ]
        
        for name, agent_class, model_path in model_configs:
            try:
                print(f"📦 Loading {name.upper()} model from {model_path}...")
                self.models[name] = agent_class.load_pretrained(
                    model_path, 
                    self.env, 
                    device=device
                )
                load_status[name] = True
                print(f"✅ {name.upper()} model loaded successfully")
            except Exception as e:
                print(f"❌ Failed to load {name.upper()} model: {e}")
                load_status[name] = False
        
        self.models_loaded = any(load_status.values())
        
        if self.models_loaded:
            print(f"🎉 RL service initialized with {sum(load_status.values())}/3 models")
        else:
            print("⚠️ No models loaded - baseline fallback only")
        
        return load_status
    
    def get_recommendation(
        self,
        state_vector: np.ndarray,
        mastery_dict: Dict[str, float],
        language_id: str,
        strategy: str = "ppo",
        deterministic: bool = True
    ) -> Dict:
        """
        Get curriculum recommendation using specified RL strategy.
        
        Args:
            state_vector: 38D state vector from StateVectorGenerator
            mastery_dict: Current mastery scores {mapping_id: score}
            language_id: Target language (python_3, javascript_es6, etc.)
            strategy: Model strategy (ppo, dqn, a2c, ensemble, baseline)
            deterministic: Use deterministic policy (True for production)
        
        Returns:
            Dict with keys: mapping_id, major_topic_id, difficulty, action_id, 
            strategy_used, confidence, metadata (prerequisite_check, violations)
        """
        
        # Validate language
        if language_id not in self.config.valid_languages:
            raise ValueError(
                f"Invalid language_id: {language_id}. "
                f"Must be one of {self.config.valid_languages}"
            )
        
        # Strategy routing
        if strategy == "baseline" or not self.models_loaded:
            return self._baseline_fallback(mastery_dict, language_id)
        
        if strategy == "ensemble":
            return self._ensemble_predict(
                state_vector, mastery_dict, language_id, deterministic
            )
        
        # Single model prediction
        model = self.models.get(strategy)
        if model is None:
            print(f"⚠️ Model {strategy} not available, falling back to baseline")
            return self._baseline_fallback(mastery_dict, language_id)
        
        # Predict action
        action, _states = model.predict(state_vector, deterministic=deterministic)
        action_int = int(action)
        
        # Decode action to (mapping_id, difficulty)
        mapping_id, difficulty = self.env.decode_action(action_int)
        difficulty = max(difficulty, 0.3)  # Clamp: frontend slider min=0.3 (Easy)
        
        # Check prerequisites
        violations = self._check_prerequisites(mapping_id, mastery_dict)
        
        if violations:
            # Prerequisite violation - fallback to baseline
            print(f"⚠️ Prerequisite violations for {mapping_id}: {violations}")
            baseline_result = self._baseline_fallback(mastery_dict, language_id)
            baseline_result['metadata']['rl_suggestion'] = {
                'mapping_id': mapping_id,
                'difficulty': difficulty,
                'action_id': action_int,
                'rejected_reason': 'prerequisite_violations',
                'violations': violations
            }
            return baseline_result
        
        # Convert mapping_id to language-specific major_topic_id
        major_topic_id = self.config.get_major_topic_id(language_id, mapping_id)
        
        if not major_topic_id:
            print(f"⚠️ Could not find major_topic_id for {language_id}/{mapping_id}")
            return self._baseline_fallback(mastery_dict, language_id)
        
        return {
            'mapping_id': mapping_id,
            'major_topic_id': major_topic_id,
            'difficulty': float(difficulty),
            'action_id': action_int,
            'strategy_used': strategy,
            'confidence': None,  # Could add Q-value confidence in future
            'metadata': {
                'prerequisite_check': {
                    'passed': True,
                    'violations': []
                },
                'language_id': language_id,
                'deterministic': deterministic
            }
        }
    
    def _ensemble_predict(
        self,
        state_vector: np.ndarray,
        mastery_dict: Dict[str, float],
        language_id: str,
        deterministic: bool
    ) -> Dict:
        """
        Ensemble prediction using majority voting across available models.
        
        Args:
            state_vector: 38D state vector
            mastery_dict: Current mastery scores
            language_id: Target language
            deterministic: Use deterministic policy
        
        Returns:
            Recommendation dict from majority vote
        """
        predictions = []
        
        for name, model in self.models.items():
            if model is not None:
                try:
                    action, _ = model.predict(state_vector, deterministic=deterministic)
                    predictions.append((name, int(action)))
                except Exception as e:
                    print(f"⚠️ {name.upper()} prediction failed: {e}")
        
        if not predictions:
            print("⚠️ All models failed, using baseline")
            return self._baseline_fallback(mastery_dict, language_id)
        
        # Count action votes
        action_votes = {}
        for model_name, action in predictions:
            action_votes[action] = action_votes.get(action, 0) + 1
        
        # Get majority action
        majority_action = max(action_votes, key=action_votes.get)
        vote_count = action_votes[majority_action]
        
        # Decode action
        mapping_id, difficulty = self.env.decode_action(majority_action)
        difficulty = max(difficulty, 0.3)  # Clamp: frontend slider min=0.3 (Easy)
        
        # Check prerequisites
        violations = self._check_prerequisites(mapping_id, mastery_dict)
        
        if violations:
            print(f"⚠️ Ensemble suggestion {mapping_id} violates prerequisites: {violations}")
            baseline_result = self._baseline_fallback(mastery_dict, language_id)
            baseline_result['metadata']['ensemble_suggestion'] = {
                'mapping_id': mapping_id,
                'difficulty': difficulty,
                'votes': f"{vote_count}/{len(predictions)}",
                'rejected_reason': 'prerequisite_violations',
                'violations': violations
            }
            return baseline_result
        
        # Convert to major_topic_id
        major_topic_id = self.config.get_major_topic_id(language_id, mapping_id)
        
        if not major_topic_id:
            print(f"⚠️ Could not find major_topic_id for {language_id}/{mapping_id}")
            return self._baseline_fallback(mastery_dict, language_id)
        
        return {
            'mapping_id': mapping_id,
            'major_topic_id': major_topic_id,
            'difficulty': float(difficulty),
            'action_id': majority_action,
            'strategy_used': 'ensemble',
            'confidence': vote_count / len(predictions),
            'metadata': {
                'prerequisite_check': {
                    'passed': True,
                    'violations': []
                },
                'language_id': language_id,
                'votes': f"{vote_count}/{len(predictions)}",
                'participating_models': [name for name, _ in predictions]
            }
        }
    
    def _baseline_fallback(
        self,
        mastery_dict: Dict[str, float],
        language_id: str
    ) -> Dict:
        """
        Rule-based baseline recommendation when RL models unavailable or fail.
        Uses lowest mastery topic that meets prerequisites.
        
        Args:
            mastery_dict: Current mastery scores {mapping_id: score}
            language_id: Target language
        
        Returns:
            Recommendation dict with baseline strategy
        """
        # Sort topics by mastery (lowest first)
        sorted_topics = sorted(
            mastery_dict.items(),
            key=lambda x: x[1]
        )
        
        # Find lowest mastery topic with prerequisites met
        for mapping_id, mastery_score in sorted_topics:
            violations = self._check_prerequisites(mapping_id, mastery_dict)
            if not violations:
                # Prerequisites met - recommend this topic
                major_topic_id = self.config.get_major_topic_id(language_id, mapping_id)
                
                if not major_topic_id:
                    continue  # Skip if can't convert to major_topic_id
                
                # Set difficulty slightly above current mastery
                target_difficulty = min(mastery_score + 0.1, 1.0)
                
                # Snap to nearest tier
                tiers = np.array([0.2, 0.4, 0.6, 0.8, 1.0])
                difficulty = float(tiers[np.argmin(np.abs(tiers - target_difficulty))])
                difficulty = max(difficulty, 0.3)  # Clamp: frontend slider min=0.3 (Easy)
                
                return {
                    'mapping_id': mapping_id,
                    'major_topic_id': major_topic_id,
                    'difficulty': difficulty,
                    'action_id': -1,  # No RL action
                    'strategy_used': 'baseline',
                    'confidence': None,
                    'metadata': {
                        'prerequisite_check': {
                            'passed': True,
                            'violations': []
                        },
                        'language_id': language_id,
                        'reason': 'rule_based_lowest_mastery',
                        'current_mastery': mastery_score
                    }
                }
        
        # Fallback: If all topics have violations, recommend first universal topic
        first_mapping = "UNIV_SYN_LOGIC"
        major_topic_id = self.config.get_major_topic_id(language_id, first_mapping)
        
        return {
            'mapping_id': first_mapping,
            'major_topic_id': major_topic_id,
            'difficulty': 0.2,
            'action_id': -1,
            'strategy_used': 'baseline',
            'confidence': None,
            'metadata': {
                'prerequisite_check': {
                    'passed': True,
                    'violations': []
                },
                'language_id': language_id,
                'reason': 'default_starter_topic',
                'current_mastery': mastery_dict.get(first_mapping, 0.0)
            }
        }
    
    def _check_prerequisites(
        self,
        mapping_id: str,
        mastery_dict: Dict[str, float]
    ) -> List[str]:
        """
        Check if prerequisites are met for given topic.
        Uses soft gates from transition_map.json.
        
        Args:
            mapping_id: Universal topic ID (UNIV_VAR, etc.)
            mastery_dict: Current mastery scores
        
        Returns:
            List of violation strings (empty if no violations)
        """
        gate = self.config.get_soft_gate(mapping_id)
        if not gate:
            return []  # No gate defined = no prerequisites
        
        violations = []
        prereq_mappings = gate['prerequisite_mappings']
        min_score = gate['minimum_allowable_score']
        
        for prereq_id in prereq_mappings:
            current_mastery = mastery_dict.get(prereq_id, 0.0)
            if current_mastery < min_score:
                violations.append(
                    f"{prereq_id} (has {current_mastery:.2f}, needs {min_score:.2f})"
                )
        
        return violations
    
    def get_health_status(self) -> Dict:
        """
        Get health status of RL service and loaded models.
        
        Returns:
            Dict with service health information
        """
        return {
            'service': 'rl_model_service',
            'status': 'healthy' if self.models_loaded else 'degraded',
            'models_loaded': {
                name: model is not None 
                for name, model in self.models.items()
            },
            'environment_ready': self.env is not None,
            'available_strategies': self._get_available_strategies()
        }
    
    def _get_available_strategies(self) -> List[str]:
        """Get list of currently available strategies."""
        strategies = ['baseline']  # Always available
        
        if self.models_loaded:
            for name, model in self.models.items():
                if model is not None:
                    strategies.append(name)
            
            # Ensemble requires at least 2 models
            loaded_count = sum(1 for m in self.models.values() if m is not None)
            if loaded_count >= 2:
                strategies.append('ensemble')
        
        return strategies


@lru_cache(maxsize=1)
def get_rl_service() -> RLModelService:
    """
    Get singleton instance of RLModelService.
    Uses lru_cache for consistent singleton behavior.
    
    Returns:
        RLModelService singleton instance
    """
    return RLModelService()
