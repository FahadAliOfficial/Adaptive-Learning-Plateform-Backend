"""
Multi-Level Analytics Service - Provides detailed error pattern analysis across topics and subtopics.

This service analyzes student performance at multiple granularities:
1. Major Topics (mapping_id level)
2. Sub-Topics (sub_topic level) 
3. Error Patterns (error_type level)
4. Cross-analysis (which errors occur most in which sub-topics)
"""

from typing import Dict, List, Optional, Tuple, Any
from sqlalchemy.orm import Session
from sqlalchemy import text
from collections import defaultdict, Counter
from .config import get_config


class MultiLevelAnalyticsService:
    """
    Advanced analytics for understanding student learning patterns.
    
    Provides insights like:
    - "Student struggles with OFF_BY_ONE_ERROR specifically in for_loop_basics"
    - "SCOPE_MISUNDERSTANDING is common in nested_loops but rare in basic_loops"
    - "This student needs targeted practice in variable_scope sub-topic"
    """
    
    def __init__(self, db_session: Session):
        self.db = db_session
        self.config = get_config()
    
    def get_student_error_profile(self, user_id: str, language_id: str) -> Dict[str, Any]:
        """
        Get comprehensive error analysis for a specific student.
        
        Returns:
        {
            "major_topic_performance": {...},
            "sub_topic_error_patterns": {...},
            "most_common_errors": [...],
            "improvement_areas": [...],
            "mastery_gaps": [...]
        }
        """
        # Get all session history for this student
        history_query = text("""
            SELECT session_snapshot FROM user_state_vectors 
            WHERE user_id = :user_id AND language_id = :language_id
            ORDER BY last_updated DESC
        """)
        
        sessions = self.db.execute(history_query, {
            "user_id": user_id, 
            "language_id": language_id
        }).fetchall()
        
        if not sessions:
            return {"error": "No session data found"}
        
        # Aggregate all question results across sessions
        all_questions = []
        for session_row in sessions:
            session_data = session_row[0]  # JSON column
            questions = session_data.get('questions', [])
            all_questions.extend(questions)
        
        return {
            "major_topic_performance": self._analyze_major_topic_performance(all_questions),
            "sub_topic_error_patterns": self._analyze_sub_topic_errors(all_questions),
            "most_common_errors": self._get_most_common_errors(all_questions),
            "improvement_areas": self._identify_improvement_areas(all_questions),
            "mastery_gaps": self._find_mastery_gaps(user_id, language_id, all_questions)
        }
    
    def get_sub_topic_error_distribution(self, language_id: str, sub_topic: str) -> Dict[str, Any]:
        """
        Analyze error patterns specific to a sub-topic across all students.
        
        Example: "In for_loop_basics, 60% of errors are OFF_BY_ONE_ERROR"
        """
        # Get all questions for this sub-topic from question bank
        question_query = text("""
            SELECT id FROM question_bank 
            WHERE language_id = :lang_id AND sub_topic = :sub_topic
        """)
        
        question_ids = [row[0] for row in self.db.execute(question_query, {
            "lang_id": language_id,
            "sub_topic": sub_topic
        }).fetchall()]
        
        if not question_ids:
            return {"error": f"No questions found for sub_topic: {sub_topic}"}
        
        # Get all user sessions that include these questions
        error_counts = Counter()
        total_attempts = 0
        incorrect_attempts = 0
        
        # Query all user state vectors for this language
        user_query = text("""
            SELECT session_snapshot FROM user_state_vectors 
            WHERE language_id = :lang_id
        """)
        
        sessions = self.db.execute(user_query, {"lang_id": language_id}).fetchall()
        
        for session_row in sessions:
            session_data = session_row[0]
            questions = session_data.get('questions', [])
            
            for q in questions:
                q_id = q.get('q_id')
                if q_id in question_ids:
                    total_attempts += 1
                    if not q.get('is_correct'):
                        incorrect_attempts += 1
                        error_type = q.get('error_type')
                        if error_type:
                            error_counts[error_type] += 1
        
        # Calculate error distribution
        error_distribution = {}
        for error_type, count in error_counts.most_common():
            percentage = (count / max(incorrect_attempts, 1)) * 100
            error_distribution[error_type] = {
                "count": count,
                "percentage": round(percentage, 1)
            }
        
        return {
            "sub_topic": sub_topic,
            "language_id": language_id,
            "total_attempts": total_attempts,
            "incorrect_attempts": incorrect_attempts,
            "accuracy_rate": round(((total_attempts - incorrect_attempts) / max(total_attempts, 1)) * 100, 1),
            "error_distribution": error_distribution,
            "most_common_error": error_counts.most_common(1)[0] if error_counts else None
        }
    
    def get_cross_topic_error_analysis(self, user_id: str, language_id: str) -> Dict[str, Any]:
        """
        Analyze how error patterns manifest across different sub-topics for a student.
        
        Example: "OFF_BY_ONE_ERROR appears in for_loops (5x) and array_access (3x)"
        """
        # Get user's session history
        history_query = text("""
            SELECT session_snapshot FROM user_state_vectors 
            WHERE user_id = :user_id AND language_id = :language_id
        """)
        
        sessions = self.db.execute(history_query, {
            "user_id": user_id,
            "language_id": language_id
        }).fetchall()
        
        # Build error -> sub_topic mapping
        error_subtopic_map = defaultdict(lambda: defaultdict(int))
        subtopic_performance = defaultdict(lambda: {"correct": 0, "total": 0})
        
        for session_row in sessions:
            session_data = session_row[0]
            questions = session_data.get('questions', [])
            
            for q in questions:
                sub_topic = q.get('sub_topic', 'unknown')
                subtopic_performance[sub_topic]["total"] += 1
                
                if q.get('is_correct'):
                    subtopic_performance[sub_topic]["correct"] += 1
                else:
                    error_type = q.get('error_type')
                    if error_type:
                        error_subtopic_map[error_type][sub_topic] += 1
        
        # Format results
        error_patterns = {}
        for error_type, subtopic_counts in error_subtopic_map.items():
            total_occurrences = sum(subtopic_counts.values())
            subtopic_breakdown = {}
            
            for subtopic, count in subtopic_counts.items():
                percentage = (count / total_occurrences) * 100
                subtopic_breakdown[subtopic] = {
                    "occurrences": count,
                    "percentage": round(percentage, 1)
                }
            
            error_patterns[error_type] = {
                "total_occurrences": total_occurrences,
                "subtopic_breakdown": dict(sorted(
                    subtopic_breakdown.items(), 
                    key=lambda x: x[1]["occurrences"], 
                    reverse=True
                ))
            }
        
        # Calculate sub-topic performance
        performance_by_subtopic = {}
        for subtopic, stats in subtopic_performance.items():
            accuracy = (stats["correct"] / max(stats["total"], 1)) * 100
            performance_by_subtopic[subtopic] = {
                "total_questions": stats["total"],
                "correct_answers": stats["correct"],
                "accuracy_percentage": round(accuracy, 1)
            }
        
        return {
            "user_id": user_id,
            "language_id": language_id,
            "error_patterns_by_subtopic": error_patterns,
            "subtopic_performance": performance_by_subtopic,
            "recommendations": self._generate_targeted_recommendations(error_patterns, performance_by_subtopic)
        }
    
    def _analyze_major_topic_performance(self, questions: List[Dict]) -> Dict[str, Any]:
        """Analyze performance at major topic (mapping_id) level."""
        topic_stats = defaultdict(lambda: {"correct": 0, "total": 0, "errors": Counter()})
        
        for q in questions:
            # Need to map sub_topic back to mapping_id
            # This would require curriculum data - simplified for now
            major_topic = self._infer_major_topic_from_subtopic(q.get('sub_topic', ''))
            
            topic_stats[major_topic]["total"] += 1
            if q.get('is_correct'):
                topic_stats[major_topic]["correct"] += 1
            else:
                error_type = q.get('error_type')
                if error_type:
                    topic_stats[major_topic]["errors"][error_type] += 1
        
        # Format results
        performance = {}
        for topic, stats in topic_stats.items():
            accuracy = (stats["correct"] / max(stats["total"], 1)) * 100
            performance[topic] = {
                "accuracy_percentage": round(accuracy, 1),
                "total_questions": stats["total"],
                "most_common_errors": dict(stats["errors"].most_common(3))
            }
        
        return performance
    
    def _analyze_sub_topic_errors(self, questions: List[Dict]) -> Dict[str, Any]:
        """Analyze error patterns within each sub-topic."""
        subtopic_errors = defaultdict(lambda: {
            "total_questions": 0,
            "incorrect_questions": 0,
            "error_breakdown": Counter()
        })
        
        for q in questions:
            sub_topic = q.get('sub_topic', 'unknown')
            subtopic_errors[sub_topic]["total_questions"] += 1
            
            if not q.get('is_correct'):
                subtopic_errors[sub_topic]["incorrect_questions"] += 1
                error_type = q.get('error_type')
                if error_type:
                    subtopic_errors[sub_topic]["error_breakdown"][error_type] += 1
        
        # Format results
        results = {}
        for subtopic, data in subtopic_errors.items():
            accuracy = ((data["total_questions"] - data["incorrect_questions"]) / 
                       max(data["total_questions"], 1)) * 100
            
            error_distribution = {}
            if data["error_breakdown"]:
                for error, count in data["error_breakdown"].items():
                    percentage = (count / max(data["incorrect_questions"], 1)) * 100
                    error_distribution[error] = {
                        "count": count,
                        "percentage": round(percentage, 1)
                    }
            
            results[subtopic] = {
                "accuracy_percentage": round(accuracy, 1),
                "total_questions": data["total_questions"],
                "error_distribution": error_distribution
            }
        
        return results
    
    def _get_most_common_errors(self, questions: List[Dict]) -> List[Dict[str, Any]]:
        """Get overall most common error patterns."""
        error_counts = Counter()
        
        for q in questions:
            if not q.get('is_correct') and q.get('error_type'):
                error_counts[q['error_type']] += 1
        
        return [
            {
                "error_type": error,
                "occurrences": count,
                "description": self._get_error_description(error)
            }
            for error, count in error_counts.most_common(10)
        ]
    
    def _identify_improvement_areas(self, questions: List[Dict]) -> List[str]:
        """Identify specific areas needing improvement."""
        # Analyze patterns to suggest targeted practice
        subtopic_accuracy = defaultdict(lambda: {"correct": 0, "total": 0})
        
        for q in questions:
            sub_topic = q.get('sub_topic', 'unknown')
            subtopic_accuracy[sub_topic]["total"] += 1
            if q.get('is_correct'):
                subtopic_accuracy[sub_topic]["correct"] += 1
        
        # Find sub-topics with low accuracy
        improvement_areas = []
        for subtopic, stats in subtopic_accuracy.items():
            accuracy = stats["correct"] / max(stats["total"], 1)
            if accuracy < 0.6 and stats["total"] >= 3:  # At least 3 attempts
                improvement_areas.append(f"Practice more {subtopic.replace('_', ' ')} (accuracy: {accuracy*100:.1f}%)")
        
        return improvement_areas
    
    def _find_mastery_gaps(self, user_id: str, language_id: str, questions: List[Dict]) -> List[str]:
        """Identify prerequisite gaps affecting current performance."""
        # This would integrate with the soft gates system
        # Simplified implementation for now
        return ["Check prerequisite understanding if accuracy remains low"]
    
    def _generate_targeted_recommendations(self, error_patterns: Dict, performance: Dict) -> List[str]:
        """Generate specific recommendations based on error analysis."""
        recommendations = []
        
        # Find most problematic error patterns
        for error_type, data in list(error_patterns.items())[:3]:  # Top 3 errors
            most_problematic_subtopic = max(
                data["subtopic_breakdown"].items(),
                key=lambda x: x[1]["occurrences"]
            )[0]
            
            recommendations.append(
                f"Focus on {error_type.replace('_', ' ').lower()} in {most_problematic_subtopic.replace('_', ' ')}"
            )
        
        return recommendations
    
    def _infer_major_topic_from_subtopic(self, sub_topic: str) -> str:
        """Map sub-topic to major topic (mapping_id)."""
        # Simplified mapping - in production this would use curriculum data
        if 'loop' in sub_topic.lower():
            return 'UNIV_LOOP'
        elif 'variable' in sub_topic.lower():
            return 'UNIV_VAR'
        elif 'function' in sub_topic.lower():
            return 'UNIV_FUNC'
        elif 'class' in sub_topic.lower() or 'object' in sub_topic.lower():
            return 'UNIV_OOP'
        else:
            return 'UNKNOWN'
    
    def _get_error_description(self, error_type: str) -> str:
        """Get human-readable description of error type."""
        descriptions = {
            'OFF_BY_ONE_ERROR': 'Loop boundaries or array indexing mistakes',
            'SCOPE_MISUNDERSTANDING': 'Variable accessibility confusion',
            'TYPE_MISMATCH': 'Incorrect data type usage',
            'MISSING_SEMICOLON': 'Forgotten statement terminators',
            'WRONG_COMPARISON_OPERATOR': 'Assignment vs comparison confusion',
            # Add more descriptions as needed
        }
        return descriptions.get(error_type, 'Programming mistake requiring attention')


# Global instance
multi_level_analytics = MultiLevelAnalyticsService