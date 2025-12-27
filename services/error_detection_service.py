"""
Error Detection Service - Maps MCQ wrong answers to error patterns.

This service bridges the gap between MCQ assessment and error pattern taxonomy
by automatically determining error_type based on student's wrong answer choice.
"""

from typing import Optional, Dict, Any, List
from .config import get_config


class ErrorDetectionService:
    """
    Detects error patterns from MCQ wrong answers.
    
    Flow:
    1. Student selects wrong answer (e.g., choice 'B')
    2. Service looks up what error pattern choice 'B' represents
    3. Returns error_type for remediation system
    """
    
    def __init__(self):
        self.config = get_config()
    
    def detect_error_from_mcq_choice(self, question_data: Dict[str, Any], selected_choice: str) -> Optional[str]:
        """
        Determine error_type based on student's wrong answer choice.
        
        Args:
            question_data: The question_data JSON from QuestionBank
            selected_choice: Student's selected answer ('A', 'B', 'C', 'D')
        
        Returns:
            error_type string from error_pattern_taxonomy, or None if correct/no mapping
        """
        options = question_data.get('options', [])
        
        # Find the selected option
        selected_option = None
        for option in options:
            if option.get('id') == selected_choice:
                selected_option = option
                break
        
        if not selected_option:
            return None
        
        # If answer was correct, no error
        if selected_option.get('is_correct', False):
            return None
        
        # Return the mapped error type for this wrong choice
        return selected_option.get('error_type')
    
    def get_error_category_from_type(self, error_type: str) -> Optional[str]:
        """
        Get the error category (e.g., 'SYNTAX_ERRORS') for a specific error_type.
        """
        if not error_type:
            return None
            
        taxonomy = self.config.transition_map.get('error_pattern_taxonomy', [])
        for category in taxonomy:
            for pattern in category.get('common_patterns', []):
                if pattern.get('error_type') == error_type:
                    return category.get('error_category')
        return None
    
    def get_remediation_suggestions(self, error_type: str, language_id: str) -> List[str]:
        """
        Get specific remediation suggestions for an error type in a language.
        """
        suggestions = []
        
        # Map common errors to learning suggestions
        remediation_map = {
            'MISSING_SEMICOLON': [
                f"Remember: {language_id} requires semicolons after statements",
                "Practice identifying where semicolons are needed",
                "Review syntax rules for statement termination"
            ],
            'OFF_BY_ONE_ERROR': [
                "Trace through loop iterations step by step",
                "Remember: arrays start at index 0",
                "Check loop conditions carefully (< vs <=)"
            ],
            'TYPE_MISMATCH': [
                f"Review {language_id} type system and casting rules",
                "Practice identifying variable types",
                "Learn when implicit conversions happen"
            ],
            'WRONG_COMPARISON_OPERATOR': [
                "Remember: = assigns, == compares",
                "Practice distinguishing assignment from comparison",
                "Review boolean expressions and conditions"
            ],
            'SCOPE_MISUNDERSTANDING': [
                "Study variable scope rules carefully",
                "Practice tracing variable visibility",
                "Learn about global vs local scope"
            ]
        }
        
        return remediation_map.get(error_type, [
            f"Review concepts related to {error_type.replace('_', ' ').lower()}",
            "Practice similar problems to reinforce understanding",
            "Study the underlying programming principles"
        ])
    
    def validate_question_error_mapping(self, question_data: Dict[str, Any]) -> List[str]:
        """
        Validate that a question has proper error type mappings.
        Returns list of validation errors, empty if valid.
        """
        errors = []
        options = question_data.get('options', [])
        
        if not options:
            errors.append("Question has no options")
            return errors
        
        correct_count = sum(1 for opt in options if opt.get('is_correct', False))
        if correct_count != 1:
            errors.append(f"Question must have exactly 1 correct answer, found {correct_count}")
        
        # Check that wrong answers have error_type mappings
        wrong_options = [opt for opt in options if not opt.get('is_correct', False)]
        unmapped_choices = []
        
        for opt in wrong_options:
            if not opt.get('error_type'):
                unmapped_choices.append(opt.get('id', 'unknown'))
        
        if unmapped_choices:
            errors.append(f"Wrong answer choices {unmapped_choices} missing error_type mapping")
        
        # Validate error types exist in taxonomy
        taxonomy_errors = self._get_valid_error_types()
        for opt in wrong_options:
            error_type = opt.get('error_type')
            if error_type and error_type not in taxonomy_errors:
                errors.append(f"Unknown error_type '{error_type}' in choice {opt.get('id')}")
        
        return errors
    
    def _get_valid_error_types(self) -> set:
        """Get all valid error_type values from taxonomy."""
        valid_types = set()
        taxonomy = self.config.transition_map.get('error_pattern_taxonomy', [])
        
        for category in taxonomy:
            for pattern in category.get('common_patterns', []):
                error_type = pattern.get('error_type')
                if error_type:
                    valid_types.add(error_type)
        
        return valid_types


# Global instance
error_detection_service = ErrorDetectionService()