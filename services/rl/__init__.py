"""
Reinforcement Learning Module for Adaptive Curriculum Sequencing.

Components:
- StudentSimulator: Generates synthetic training data
- AdaptiveLearningEnv: Gym-compatible RL environment
- PPOAgent: Proximal Policy Optimization agent
- DQNAgent: Deep Q-Network agent
- A2CAgent: Advantage Actor-Critic agent
"""

from .student_simulator import StudentSimulator, StudentProfile, UNIVERSAL_MAPPINGS
from .adaptive_learning_env import AdaptiveLearningEnv
from .ppo_agent import PPOAgent
from .dqn_agent import DQNAgent
from .a2c_agent import A2CAgent

__all__ = [
    'StudentSimulator',
    'StudentProfile',
    'UNIVERSAL_MAPPINGS',
    'AdaptiveLearningEnv',
    'PPOAgent',
    'DQNAgent',
    'A2CAgent'
]
