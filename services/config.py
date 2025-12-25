"""
Configuration loader for curriculum and transition map.
Ensures single source of truth for all backend services.
"""

import json
from pathlib import Path
from typing import Dict, List, Any
from functools import lru_cache


class CurriculumConfig:
    """Loads and validates curriculum.json and transition_map.json."""
    
    def __init__(self, curriculum_path: str, transition_path: str):
        self.curriculum_path = Path(curriculum_path)
        self.transition_path = Path(transition_path)
        
        # Load JSON files
        with open(self.curriculum_path, 'r', encoding='utf-8') as f:
            self.curriculum = json.load(f)
        
        with open(self.transition_path, 'r', encoding='utf-8') as f:
            self.transition_map = json.load(f)
        
        # Build lookup indices
        self._build_indices()
    
    def _build_indices(self):
        """Create fast lookup dictionaries."""
        # Language ID validation
        self.valid_languages = {lang['language_id'] for lang in self.curriculum}
        
        # Mapping ID to language lookup
        self.mapping_to_topics = {}  # {mapping_id: {lang_id: major_topic_id}}
        
        # Universal mapping IDs in order
        self.universal_mappings = []
        
        for lang in self.curriculum:
            lang_id = lang['language_id']
            for topic in lang['roadmap']:
                mapping_id = topic['mapping_id']
                major_id = topic['major_topic_id']
                
                if mapping_id not in self.mapping_to_topics:
                    self.mapping_to_topics[mapping_id] = {}
                    if mapping_id not in self.universal_mappings:
                        self.universal_mappings.append(mapping_id)
                
                self.mapping_to_topics[mapping_id][lang_id] = {
                    'major_topic_id': major_id,
                    'name': topic['name'],
                    'difficulty': topic['global_difficulty'],
                    'prerequisites': topic['prerequisites']
                }
    
    def get_mapping_id(self, language_id: str, major_topic_id: str) -> str:
        """Convert language-specific topic to universal mapping."""
        for lang in self.curriculum:
            if lang['language_id'] == language_id:
                for topic in lang['roadmap']:
                    if topic['major_topic_id'] == major_topic_id:
                        return topic['mapping_id']
        raise ValueError(f"Topic {major_topic_id} not found in {language_id}")
    
    def get_topic_prerequisites(self, language_id: str, major_topic_id: str) -> List[str]:
        """Get prerequisite major_topic_ids for a given topic."""
        for lang in self.curriculum:
            if lang['language_id'] == language_id:
                for topic in lang['roadmap']:
                    if topic['major_topic_id'] == major_topic_id:
                        return topic['prerequisites']
        return []
    
    def get_synergy_bonuses(self, trigger_mapping_id: str) -> List[Dict[str, Any]]:
        """Get synergy bonuses triggered by mastering a topic."""
        return [
            s for s in self.transition_map['intra_language_synergy']
            if s['trigger_mapping_id'] == trigger_mapping_id
        ]
    
    def get_soft_gate(self, mapping_id: str) -> Dict[str, Any]:
        """Get soft gate requirements for a topic."""
        for gate in self.transition_map['soft_gates']:
            if gate['mapping_id'] == mapping_id:
                return gate
        return None
    
    def get_difficulty_tier(self, mapping_id: str, mastery_score: float) -> str:
        """Determine which difficulty tier user should practice."""
        for tier_config in self.transition_map['question_difficulty_tiers']:
            if tier_config.get('mapping_id') == mapping_id:
                tiers = tier_config['tiers']
                if mastery_score < tiers['intermediate']['min_mastery_to_unlock']:
                    return 'beginner'
                elif mastery_score < tiers['advanced']['min_mastery_to_unlock']:
                    return 'intermediate'
                else:
                    return 'advanced'
        return 'intermediate'  # Default
    
    def get_decay_rate(self) -> float:
        """Get knowledge decay rate from config."""
        return self.transition_map['config']['decay_rate_per_day']
    
    def get_review_multiplier(self) -> float:
        """Get review effectiveness multiplier."""
        return self.transition_map['config']['review_multiplier']
    
    def get_maintenance_threshold(self) -> float:
        """Get minimum mastery before review needed."""
        return self.transition_map['config']['maintenance_threshold']
    
    def get_experience_config(self, level: str) -> Dict[str, Any]:
        """Get starting configuration for experience level."""
        experience_levels = self.transition_map.get('experience_levels', {})
        # Defaults to beginner if invalid level passed
        return experience_levels.get(level, experience_levels.get('beginner', {}))
    
    def get_major_topic_id(self, language_id: str, mapping_id: str) -> str:
        """Convert universal mapping to language-specific major_topic_id."""
        topic_info = self.mapping_to_topics.get(mapping_id, {}).get(language_id)
        if topic_info:
            return topic_info['major_topic_id']
        raise ValueError(f"No major_topic_id found for {mapping_id} in {language_id}")


# Singleton instance
@lru_cache(maxsize=1)
def get_config() -> CurriculumConfig:
    """Get cached configuration instance."""
    import os
    base_path = Path(__file__).parent.parent / 'core'
    return CurriculumConfig(
        curriculum_path=str(base_path / 'final_curriculum.json'),
        transition_path=str(base_path / 'transition_map.json')
    )
