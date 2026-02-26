"""
Prerequisite Analyzer - Intelligent Prerequisite Gap Detection (Phase 2)
Analyzes student's mastery of prerequisite topics and identifies learning gaps.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session
from typing import Dict, List, Any, Optional, Tuple
from .config import get_config


class PrerequisiteAnalyzer:
    """
    Analyzes prerequisite gaps and provides targeted recommendations.
    
    Uses prerequisite_strength_weights from transition_map to determine:
    - Required prerequisite mastery thresholds
    - Impact of prerequisite gaps on current topic
    - Priority-ordered remediation suggestions
    """
    
    def __init__(self, db_session: Session):
        self.db = db_session
        self.config = get_config()
        self.transition_map = self.config.transition_map
        
        # Default mastery thresholds
        self.WEAK_THRESHOLD = 0.45    # Below this = critical gap
        self.READY_THRESHOLD = 0.65   # Above this = ready for next topic
        self.STRONG_THRESHOLD = 0.80  # Above this = strong foundation
    
    def analyze_prerequisites(
        self,
        user_id: str,
        language_id: str,
        target_mapping_id: str
    ) -> Dict[str, Any]:
        """
        Comprehensive prerequisite gap analysis for a target topic.
        
        Args:
            user_id: Student UUID
            language_id: Language identifier (python_3, javascript_es6, etc.)
            target_mapping_id: Universal mapping ID (UNIV_LOOP, UNIV_FUNC, etc.)
        
        Returns:
            {
                "target_topic": "UNIV_LOOP",
                "ready_to_learn": True/False,
                "overall_readiness": 0.72,  # Weighted average
                "critical_gaps": [
                    {
                        "prereq_id": "UNIV_VAR",
                        "name": "Variables",
                        "current_mastery": 0.40,
                        "required_mastery": 0.65,
                        "gap_size": 0.25,
                        "weight": 0.8,
                        "impact": "high",  # high/medium/low
                        "recommendation": "Review Python variables and types first"
                    }
                ],
                "gaps": [...],  # All gaps (< 0.65)
                "strong_prerequisites": [...],  # Mastery >= 0.80
                "remediation_priority": [...]  # Sorted by (gap_size * weight)
            }
        """
        
        # Get prerequisite requirements from curriculum
        prerequisites = self._get_topic_prerequisites(language_id, target_mapping_id)
        
        if not prerequisites:
            return {
                "target_topic": target_mapping_id,
                "ready_to_learn": True,
                "overall_readiness": 1.0,
                "critical_gaps": [],
                "gaps": [],
                "strong_prerequisites": [],
                "remediation_priority": []
            }
        
        # Fetch current mastery for all prerequisites
        prereq_ids = list(prerequisites.keys())
        mastery_query = text("""
            SELECT mapping_id, mastery_score
            FROM student_state
            WHERE user_id = :uid AND language_id = :lang AND mapping_id = ANY(:prereqs)
        """)
        
        mastery_rows = self.db.execute(mastery_query, {
            "uid": user_id,
            "lang": language_id,
            "prereqs": prereq_ids
        }).fetchall()
        
        # Build mastery map
        current_mastery = {row[0]: row[1] for row in mastery_rows}
        
        # Fill in 0.0 for prerequisites not yet attempted
        for prereq_id in prereq_ids:
            if prereq_id not in current_mastery:
                current_mastery[prereq_id] = 0.0
        
        # Analyze gaps
        critical_gaps = []
        gaps = []
        strong_prerequisites = []
        
        for prereq_id, weight in prerequisites.items():
            mastery = current_mastery.get(prereq_id, 0.0)
            required = self.READY_THRESHOLD
            gap_size = max(0, required - mastery)
            
            prereq_name = self._get_topic_name(language_id, prereq_id)
            
            prereq_info = {
                "prereq_id": prereq_id,
                "name": prereq_name,
                "current_mastery": round(mastery, 2),
                "required_mastery": required,
                "gap_size": round(gap_size, 2),
                "weight": weight,
                "impact": self._calculate_impact(gap_size, weight),
                "recommendation": self._generate_gap_recommendation(
                    prereq_id, prereq_name, gap_size, language_id
                )
            }
            
            if mastery < self.WEAK_THRESHOLD:
                critical_gaps.append(prereq_info)
            elif mastery < self.READY_THRESHOLD:
                gaps.append(prereq_info)
            elif mastery >= self.STRONG_THRESHOLD:
                strong_prerequisites.append(prereq_info)
        
        # Calculate weighted readiness score
        total_weight = sum(prerequisites.values())
        weighted_mastery_sum = sum(
            current_mastery.get(prereq_id, 0.0) * weight
            for prereq_id, weight in prerequisites.items()
        )
        overall_readiness = weighted_mastery_sum / total_weight if total_weight > 0 else 0.0
        
        # Sort remediation by priority (gap_size * weight)
        all_gaps = critical_gaps + gaps
        remediation_priority = sorted(
            all_gaps,
            key=lambda x: x["gap_size"] * x["weight"],
            reverse=True
        )
        
        # Determine if ready to learn
        ready_to_learn = (
            len(critical_gaps) == 0 and 
            overall_readiness >= self.READY_THRESHOLD
        )
        
        return {
            "target_topic": target_mapping_id,
            "ready_to_learn": ready_to_learn,
            "overall_readiness": round(overall_readiness, 2),
            "critical_gaps": critical_gaps,
            "gaps": gaps,
            "strong_prerequisites": strong_prerequisites,
            "remediation_priority": remediation_priority
        }
    
    def get_prerequisite_gaps_summary(
        self,
        user_id: str,
        language_id: str,
        target_mapping_id: str
    ) -> List[Dict[str, Any]]:
        """
        Simplified prerequisite gap summary for LLM prompt enrichment.
        
        Returns list of gaps suitable for passing to ExamAnalysisService:
        [
            {
                "topic": "UNIV_VAR",
                "current": 0.40,
                "required": 0.65,
                "weight": 0.8
            },
            ...
        ]
        """
        analysis = self.analyze_prerequisites(user_id, language_id, target_mapping_id)
        
        gaps_summary = []
        for gap in analysis["remediation_priority"]:
            gaps_summary.append({
                "topic": gap["prereq_id"],
                "current": gap["current_mastery"],
                "required": gap["required_mastery"],
                "weight": gap["weight"]
            })
        
        return gaps_summary
    
    def check_soft_gates(
        self,
        user_id: str,
        language_id: str,
        target_mapping_id: str
    ) -> Tuple[bool, List[str]]:
        """
        Check if student has sufficient prerequisites (soft gate check).
        
        Returns:
            (has_violations, violation_list)
            - has_violations: True if critical gaps exist
            - violation_list: List of prerequisite IDs with critical gaps
        """
        analysis = self.analyze_prerequisites(user_id, language_id, target_mapping_id)
        
        critical_gap_ids = [gap["prereq_id"] for gap in analysis["critical_gaps"]]
        has_violations = len(critical_gap_ids) > 0
        
        return has_violations, critical_gap_ids
    
    def get_next_recommended_topics(
        self,
        user_id: str,
        language_id: str,
        current_mapping_id: str
    ) -> List[Dict[str, Any]]:
        """
        Suggest next topics student should study based on current progress.
        
        Returns list of topics with readiness scores:
        [
            {
                "mapping_id": "UNIV_FUNC",
                "name": "Functions",
                "readiness": 0.85,
                "ready": True,
                "recommendation": "You're ready to start functions!"
            },
            ...
        ]
        """
        # Get all topics in order from universal transitions
        universal_mappings = self.config.universal_mappings
        current_index = universal_mappings.index(current_mapping_id) if current_mapping_id in universal_mappings else -1
        
        if current_index == -1 or current_index >= len(universal_mappings) - 1:
            return []  # No next topics available
        
        # Check next 3 topics
        next_topics = universal_mappings[current_index + 1:current_index + 4]
        recommendations = []
        
        for topic_id in next_topics:
            analysis = self.analyze_prerequisites(user_id, language_id, topic_id)
            topic_name = self._get_topic_name(language_id, topic_id)
            
            recommendations.append({
                "mapping_id": topic_id,
                "name": topic_name,
                "readiness": analysis["overall_readiness"],
                "ready": analysis["ready_to_learn"],
                "recommendation": self._generate_next_topic_recommendation(
                    topic_name, analysis["ready_to_learn"], analysis["critical_gaps"]
                )
            })
        
        return recommendations
    
    def _get_topic_prerequisites(
        self,
        language_id: str,
        mapping_id: str
    ) -> Dict[str, float]:
        """
        Get prerequisite requirements with weights.
        
        Returns: {prereq_mapping_id: weight, ...}
        
        Note: Uses language-specific prerequisites from curriculum.
        Falls back to prerequisite_strength_weights if available.
        """
        # First try curriculum prerequisites
        if mapping_id in self.config.mapping_to_topics:
            topic_info = self.config.mapping_to_topics[mapping_id].get(language_id, {})
            prereq_list = topic_info.get('prerequisites', [])
            
            if prereq_list:
                # Assign equal weights if not specified
                num_prereqs = len(prereq_list)
                return {prereq: 1.0 / num_prereqs for prereq in prereq_list}
        
        # Fallback to prerequisite_strength_weights from transition_map
        # Phase 2 Fix (Issue 1): prerequisite_strength_weights is an array, not a dict
        prereq_list = self.transition_map.get('prerequisite_strength_weights', [])
        topic_entry = next(
            (entry for entry in prereq_list if entry.get('target_mapping_id') == mapping_id),
            None
        )
        if topic_entry:
            return topic_entry.get('prerequisites', {})
        
        return {}
    
    def _get_topic_name(self, language_id: str, mapping_id: str) -> str:
        """Get human-readable topic name."""
        if mapping_id in self.config.mapping_to_topics:
            topic_info = self.config.mapping_to_topics[mapping_id].get(language_id, {})
            return topic_info.get('name', mapping_id)
        return mapping_id.replace('UNIV_', '').replace('_', ' ').title()
    
    def _calculate_impact(self, gap_size: float, weight: float) -> str:
        """Categorize gap impact as high/medium/low."""
        impact_score = gap_size * weight
        
        if impact_score >= 0.25:
            return "high"
        elif impact_score >= 0.15:
            return "medium"
        else:
            return "low"
    
    def _generate_gap_recommendation(
        self,
        prereq_id: str,
        prereq_name: str,
        gap_size: float,
        language_id: str
    ) -> str:
        """Generate actionable recommendation for closing a gap."""
        lang_name = self._get_language_display_name(language_id)
        
        if gap_size >= 0.4:
            return f"Start with {lang_name} {prereq_name} basics - this is a foundational topic"
        elif gap_size >= 0.2:
            return f"Review {lang_name} {prereq_name} concepts to strengthen your foundation"
        else:
            return f"Quick refresher on {lang_name} {prereq_name} recommended"
    
    def _generate_next_topic_recommendation(
        self,
        topic_name: str,
        ready: bool,
        critical_gaps: List[Dict]
    ) -> str:
        """Generate recommendation for next topic."""
        if ready:
            return f"You're ready to start {topic_name}! Your prerequisites are strong."
        elif len(critical_gaps) > 0:
            gap_list = ", ".join([g["name"] for g in critical_gaps[:2]])
            return f"Review {gap_list} first before starting {topic_name}"
        else:
            return f"Almost ready for {topic_name}. Practice current topics a bit more."
    
    def _get_language_display_name(self, language_id: str) -> str:
        """Convert language_id to display name."""
        name_map = {
            'python_3': 'Python',
            'javascript_es6': 'JavaScript',
            'java_17': 'Java',
            'cpp_20': 'C++',
            'go_1_21': 'Go',
            'typescript_5': 'TypeScript'
        }
        return name_map.get(language_id, language_id)
