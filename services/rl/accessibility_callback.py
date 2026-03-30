"""
Custom callback to track action masking metrics during RL training.

Tracks:
- train/avg_accessible_actions: Average number of valid actions available per state  
- train/accessibility_violations_pct: % of episodes that end due to invalid action attempts

These metrics ensure the RL model respects curriculum prerequisites.
"""

import numpy as np
from stable_baselines3.common.callbacks import BaseCallback
from stable_baselines3.common.vec_env import DummyVecEnv, VecEnv


class AccessibilityMetricsCallback(BaseCallback):
    """
    Callback to track accessibility metrics during training.
    
    This callback monitors:
    1. Average accessible actions - mean number of valid actions per state
    2. Accessibility violations - % of episodes truncated due to invalid actions
    
    These metrics are logged to TensorBoard and help verify that the RL
    model properly respects curriculum prerequisites after retraining.
    
    Target after retraining:
    - avg_accessible_actions: 5-8 actions (down from 40 total)
    - accessibility_violations_pct: 0% (model never attempts locked topics)
    
    Example Usage:
        >>> callback = AccessibilityMetricsCallback(check_freq=1000)
        >>> model.learn(..., callback=callback)
    """
    
    def __init__(self, check_freq: int = 1000, verbose: int = 0):
        """
        Args:
            check_freq: Log metrics every N steps (default: 1000)
            verbose: Verbosity level (0=quiet, 1=info, 2=debug)
        """
        super().__init__(verbose)
        self.check_freq = check_freq
        self.accessible_actions_buffer = []
        self.violation_count = 0
        self.episode_count = 0
    
    def _on_step(self) -> bool:
        """
        Called after each environment step during training.
        
        Tracks action masking statistics from the environment.
        """
        # Get the underlying environment (unwrap vectorized wrapper)
        env = self.training_env
        if isinstance(env, (DummyVecEnv, VecEnv)):
            # Access first environment in vectorized wrapper
            if hasattr(env, 'envs'):
                env = env.envs[0]
            elif hasattr(env, 'venv'):
                env = env.venv.envs[0]
        
        # Check if environment supports action masking
        if hasattr(env, 'action_masks'):
            # Get current action mask
            mask = env.action_masks()
            
            # Count accessible actions (mask=1 means valid)
            num_accessible = np.sum(mask)
            self.accessible_actions_buffer.append(num_accessible)
        
        # Check if episode ended
        if self.locals.get('dones', [False])[0]:
            self.episode_count += 1
            
            # Check if it was due to accessibility violation
            infos = self.locals.get('infos', [{}])
            if len(infos) > 0 and infos[0].get('error') == 'invalid_action':
                self.violation_count += 1
        
        # Log metrics periodically
        if self.num_timesteps % self.check_freq == 0 and len(self.accessible_actions_buffer) > 0:
            # Calculate averages
            avg_accessible = np.mean(self.accessible_actions_buffer)
            violation_pct = (self.violation_count / self.episode_count * 100) if self.episode_count > 0 else 0.0
            
            # Log to TensorBoard
            self.logger.record("train/avg_accessible_actions", avg_accessible)
            self.logger.record("train/accessibility_violations_pct", violation_pct)
            
            if self.verbose >= 1:
                print(f"  [Step {self.num_timesteps:>7}] Accessible: {avg_accessible:.1f} actions/state, "
                      f"Violations: {violation_pct:.1f}% ({self.violation_count}/{self.episode_count} episodes)")
            
            # Reset buffers
            self.accessible_actions_buffer = []
            self.violation_count = 0
            self.episode_count = 0
        
        return True  # Continue training
