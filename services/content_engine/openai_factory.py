"""
OpenAI GPT-4o-mini integration for MCQ generation.
Implements retry logic, rate limiting, and safety checks.

Replaces Gemini with OpenAI for question generation.
"""
import openai
import json
import os
from typing import Dict, Optional, List
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from datetime import datetime, timezone
import re

from services.content_engine.validator import MultiLanguageValidator


class OpenAIFactory:
    """
    Generates MCQ questions using OpenAI GPT-4o-mini.
    
    Features:
    - Automatic retry on failures (exponential backoff)
    - Prompt injection prevention
    - Multi-language support
    - Quality validation before storage
    - Sub-topic control for curriculum coverage
    """
    
    # Model configuration
    MODEL_NAME = "gpt-4o-mini"
    TEMPERATURE = 0.7  # Balance creativity with consistency
    
    def __init__(self):
        self.client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    
    @staticmethod
    def sanitize_topic(topic: str) -> str:
        """
        Prevent prompt injection attacks.
        
        Blocks:
        - System prompts ("ignore previous instructions")
        - Code execution attempts
        - Excessive length
        
        Returns:
            Sanitized topic string
        
        Raises:
            ValueError: If topic is malicious
        """
        # Length check
        if len(topic) > 100:
            raise ValueError("Topic too long (max 100 characters)")
        
        # Injection pattern detection
        dangerous_patterns = [
            r'ignore.*(previous|all|any).*(instructions?|prompts?)',
            r'system\s*:',
            r'<script',
            r'javascript:',
            r'eval\(',
            r'exec\(',
            r'__import__',
            r'subprocess',
            r'os\.system'
        ]
        
        for pattern in dangerous_patterns:
            if re.search(pattern, topic, re.IGNORECASE):
                raise ValueError(f"Potential prompt injection detected: {pattern}")
        
        # Sanitize: keep only alphanumeric, spaces, and basic punctuation
        sanitized = re.sub(r'[^a-zA-Z0-9\s\-_.,():]', '', topic)
        
        return sanitized.strip()
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((Exception,)),
        reraise=True
    )
    def generate_question(
        self,
        topic: str,
        language_id: str,
        mapping_id: str,
        difficulty: float,
        sub_topic: Optional[str] = None
    ) -> Dict:
        """
        Generate a single MCQ using OpenAI GPT-4o-mini.
        
        Args:
            topic: Human-readable topic (e.g., "for loops")
            language_id: "python_3", "javascript_es6", etc.
            mapping_id: Curriculum node (e.g., "UNIV_LOOP")
            difficulty: 0.0 (easy) to 1.0 (hard)
            sub_topic: Optional refinement (e.g., "nested loops")
        
        Returns:
            {
                "question_text": str,
                "code_snippet": str (optional),
                "options": [{"id": str, "text": str, "is_correct": bool}],
                "explanation": str,
                "quality_score": float
            }
        
        Raises:
            ValueError: If topic is malicious or response invalid
            Exception: If API fails after retries
        """
        # 1. Sanitize input
        safe_topic = self.sanitize_topic(topic)
        
        # 2. Build language-specific prompt
        system_prompt, user_prompt = self._build_prompt(
            safe_topic, language_id, mapping_id, difficulty, sub_topic
        )
        
        # 3. Retry loop for quality validation
        max_quality_retries = 3
        for attempt in range(max_quality_retries):
            try:
                # 4. Call OpenAI API (with auto-retry via @retry decorator)
                response = self.client.chat.completions.create(
                    model=self.MODEL_NAME,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    temperature=self.TEMPERATURE,
                    max_tokens=2048,
                    response_format={"type": "json_object"},  # Enforce JSON output
                    timeout=30
                )
                
                # 5. Extract JSON from response
                raw_text = response.choices[0].message.content
                question_data = self._parse_response(raw_text)
                
                # 6. Validate option quality
                is_valid, error = MultiLanguageValidator.validate_option_quality(question_data)
                if not is_valid:
                    if attempt < max_quality_retries - 1:
                        print(f"⚠️ Option quality failed ({error}), retrying ({attempt+1}/{max_quality_retries})...")
                        continue  # Retry generation
                    else:
                        raise ValueError(f"Failed to generate quality options after {max_quality_retries} attempts: {error}")
                
                # 7. Validate syntax (if code present)
                if question_data.get('code_snippet'):
                    is_valid, error = MultiLanguageValidator.validate_syntax(
                        question_data['code_snippet'],
                        language_id
                    )
                    if not is_valid:
                        if attempt < max_quality_retries - 1:
                            print(f"⚠️ Syntax validation failed ({error}), retrying...")
                            continue
                        else:
                            raise ValueError(f"Generated code has syntax error: {error}")
                
                # 8. Add metadata
                question_data['language_id'] = language_id
                question_data['mapping_id'] = mapping_id
                question_data['difficulty'] = difficulty
                question_data['sub_topic'] = sub_topic
                
                # 9. Quality self-assessment (parse from AI response)
                question_data['quality_score'] = self._extract_quality_score(raw_text)
                
                return question_data
            
            except Exception as e:
                if attempt >= max_quality_retries - 1:
                    raise
                print(f"⚠️ Generation attempt {attempt+1} failed: {e}")
        
        raise ValueError("Failed to generate valid question after all retries")
    
    def _build_prompt(
        self,
        topic: str,
        language_id: str,
        mapping_id: str,
        difficulty: float,
        sub_topic: Optional[str]
    ) -> tuple[str, str]:
        """
        Construct engineered prompt for OpenAI.
        Returns (system_prompt, user_prompt).
        """
        # Map language_id to human name (versions match Docker compiler versions)
        lang_map = {
            "python_3": "Python 3.11",
            "javascript_es6": "JavaScript (ES6+/Node 20)",
            "java_17": "Java 13",  # ID kept for compatibility, actual compiler is Java 13.0.1
            "cpp_20": "C++17",     # ID kept for compatibility, actual compiler is GCC 8.3 (C++17 max)
            "go_1_21": "Go 1.21"
        }
        lang_name = lang_map.get(language_id, language_id)
        
        # Map difficulty to description
        if difficulty < 0.3:
            diff_desc = "beginner-level"
        elif difficulty < 0.7:
            diff_desc = "intermediate-level"
        else:
            diff_desc = "advanced-level"
        
        # Build topic description with sub-topic control
        if sub_topic:
            topic_desc = f"{topic} (FOCUS EXCLUSIVELY ON: {sub_topic})"
            subtopic_constraint = f"""
**CRITICAL CONSTRAINT:**
You MUST create a question that tests ONLY the sub-topic: **{sub_topic}**
Do NOT mix multiple sub-topics in one question.
Do NOT create generic questions that could fit any sub-topic.

Example:
- ✅ GOOD: If sub-topic is "nested_loops", ask about 2D arrays or nested iteration
- ❌ BAD: If sub-topic is "nested_loops", don't ask about basic for loop syntax
"""
        else:
            topic_desc = f"{topic}"
            subtopic_constraint = ""
        
        system_prompt = """You are an expert computer science educator creating multiple-choice questions for adaptive learning systems. 

You MUST respond with valid JSON only. Use this exact structure:
{
  "question_text": "...",
  "code_snippet": "... or null",
  "options": [
    {"id": "A", "text": "...", "is_correct": true/false, "error_type": "..." or null},
    {"id": "B", "text": "...", "is_correct": true/false, "error_type": "..." or null},
    {"id": "C", "text": "...", "is_correct": true/false, "error_type": "..." or null},
    {"id": "D", "text": "...", "is_correct": true/false, "error_type": "..." or null}
  ],
  "explanation": "...",
  "quality_assessment": {
    "score": 0.8,
    "reasoning": "..."
  }
}

ERROR TYPES for wrong answers:
SYNTAX_ERRORS, TYPE_ERRORS, LOGIC_ERRORS, LOOP_ERRORS, FUNCTION_ERRORS, COLLECTION_ERRORS, OOP_ERRORS, MEMORY_ERRORS, SCOPE_MISUNDERSTANDING, OFF_BY_ONE_ERROR, TYPE_MISMATCH, WRONG_COMPARISON_OPERATOR, LANGUAGE_CONFUSION_ERROR, INDEX_OUT_OF_BOUNDS, MISSING_SEMICOLON, NULL_POINTER_DEREFERENCE, INFINITE_LOOP, WRONG_VARIABLE_SCOPE"""
        
        user_prompt = f"""Create ONE high-quality MCQ about **{topic_desc}** in **{lang_name}** at **{diff_desc}** difficulty.

{subtopic_constraint}

**Requirements:**
1. Question must be clear and unambiguous
2. Choose the most effective format:
   - **Code-based**: Include a code snippet for output/behavior questions
   - **Conceptual**: Focus on understanding without code for theory/principles
   - **Scenario-based**: Describe a programming situation
3. Exactly 4 options (A, B, C, D) with ONE correct answer
4. Options test understanding, not memorization  
5. Include brief explanation of the correct answer
6. If using code, it must be syntactically correct and runnable
7. Avoid trivial questions

**Distractor Design:**
Each wrong answer must:
- Map to a specific error_type from the list
- Be plausible enough for beginners
- Be clearly wrong to those who understand

**FORBIDDEN OPTIONS:**
❌ "None of the above"
❌ "All of the above" 
❌ "I don't know"
❌ "Cannot determine"

**Difficulty Guidelines:**
- Beginner (0.0-0.3): Basic syntax, single concept
- Intermediate (0.3-0.7): Multiple concepts, logic required
- Advanced (0.7-1.0): Edge cases, performance, design patterns

Return ONLY valid JSON matching the structure in your system instructions."""
        
        return system_prompt, user_prompt
    
    def _parse_response(self, raw_text: str) -> Dict:
        """
        Extract JSON from OpenAI response.
        """
        text = raw_text.strip()
        
        # Parse JSON
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise ValueError(f"AI response is not valid JSON: {e}\n\nResponse:\n{raw_text}")
        
        # Validate required fields
        required = ["question_text", "options", "explanation"]
        for field in required:
            if field not in data:
                raise ValueError(f"Missing required field: {field}")
        
        # Validate options structure
        if not isinstance(data['options'], list) or len(data['options']) != 4:
            raise ValueError("Must have exactly 4 options")
        
        for opt in data['options']:
            if not all(k in opt for k in ['id', 'text', 'is_correct']):
                raise ValueError(f"Invalid option structure: {opt}")
            
            # Validate error_type for wrong answers
            if not opt['is_correct'] and 'error_type' not in opt:
                print(f"Warning: Wrong answer {opt['id']} missing error_type mapping")
        
        # Ensure exactly one correct answer
        correct_count = sum(1 for opt in data['options'] if opt['is_correct'])
        if correct_count != 1:
            raise ValueError(f"Must have exactly 1 correct answer, got {correct_count}")
        
        return data
    
    def _extract_quality_score(self, raw_text: str) -> float:
        """
        Extract AI's self-assessed quality score.
        Falls back to 0.5 if not present.
        """
        try:
            data = json.loads(raw_text.strip())
            if 'quality_assessment' in data and 'score' in data['quality_assessment']:
                score = float(data['quality_assessment']['score'])
                return max(0.0, min(1.0, score))  # Clamp to [0, 1]
        except Exception:
            pass
        
        return 0.5  # Default fallback
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((Exception,)),
        reraise=True
    )
    def generate_batch(
        self,
        topic: str,
        language_id: str,
        mapping_id: str,
        difficulty: float,
        count: int = 10,
        sub_topic: Optional[str] = None
    ) -> List[Dict]:
        """
        Generate multiple questions in a SINGLE API call (more efficient).
        
        Args:
            count: Number of questions to generate (1-20 recommended per call)
        
        Returns:
            List of question dictionaries with validation applied
        """
        # Sanitize input
        safe_topic = self.sanitize_topic(topic)
        
        # Build batch prompt
        system_prompt, user_prompt = self._build_batch_prompt(
            safe_topic, language_id, mapping_id, difficulty, count, sub_topic
        )
        
        # Single API call for all questions
        response = self.client.chat.completions.create(
            model=self.MODEL_NAME,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=self.TEMPERATURE,
            max_tokens=4096 if count <= 10 else 8192,  # Scale token limit
            response_format={"type": "json_object"},
            timeout=60
        )
        
        # Parse batch response
        raw_text = response.choices[0].message.content
        batch_data = self._parse_batch_response(raw_text, count)
        
        # Validate and enrich each question
        validated_questions = []
        seen_hashes = set()
        
        for idx, q_data in enumerate(batch_data['questions']):
            try:
                # Validate options quality
                is_valid, error = MultiLanguageValidator.validate_option_quality(q_data)
                if not is_valid:
                    print(f"⚠️ Question {idx+1} failed validation: {error}")
                    continue
                
                # Validate syntax if code present
                if q_data.get('code_snippet'):
                    is_valid, error = MultiLanguageValidator.validate_syntax(
                        q_data['code_snippet'], language_id
                    )
                    if not is_valid:
                        print(f"⚠️ Question {idx+1} has syntax error: {error}")
                        continue
                
                # Add metadata
                q_data['language_id'] = language_id
                q_data['mapping_id'] = mapping_id
                q_data['difficulty'] = difficulty
                q_data['sub_topic'] = sub_topic
                q_data['quality_score'] = q_data.get('quality_score', 0.7)
                
                # Deduplicate
                content_hash = MultiLanguageValidator.generate_content_hash(q_data)
                if content_hash in seen_hashes:
                    print(f"⚠️ Question {idx+1} is duplicate, skipping")
                    continue
                
                q_data['content_hash'] = content_hash
                seen_hashes.add(content_hash)
                validated_questions.append(q_data)
                
            except Exception as e:
                print(f"⚠️ Question {idx+1} processing error: {e}")
                continue
        
        print(f"✅ Generated {len(validated_questions)}/{count} valid unique questions")
        return validated_questions
    
    def _build_batch_prompt(
        self,
        topic: str,
        language_id: str,
        mapping_id: str,
        difficulty: float,
        count: int,
        sub_topic: Optional[str]
    ) -> tuple[str, str]:
        """
        Construct optimized batch prompt for multiple questions in one call.
        """
        lang_map = {
            "python_3": "Python 3.11",
            "javascript_es6": "JavaScript (ES6+/Node 20)",
            "java_17": "Java 13",  # ID kept for compatibility, actual compiler is Java 13.0.1
            "cpp_20": "C++17",     # ID kept for compatibility, actual compiler is GCC 8.3 (C++17 max)
            "go_1_21": "Go 1.21"
        }
        lang_name = lang_map.get(language_id, language_id)
        
        if difficulty < 0.3:
            diff_desc = "beginner"
        elif difficulty < 0.7:
            diff_desc = "intermediate"
        else:
            diff_desc = "advanced"
        
        topic_focus = f"{topic} (focus: {sub_topic})" if sub_topic else topic
        
        system_prompt = f"""Expert CS educator creating {count} diverse MCQs for adaptive learning in {lang_name}.

Respond with valid JSON:
{{
  "questions": [
    {{
      "question_text": "...",
      "code_snippet": "...",
      "options": [
        {{"id": "A", "text": "...", "is_correct": true/false, "error_type": "..."}},
        {{"id": "B", "text": "...", "is_correct": true/false, "error_type": "..."}},
        {{"id": "C", "text": "...", "is_correct": true/false, "error_type": "..."}},
        {{"id": "D", "text": "...", "is_correct": true/false, "error_type": "..."}}
      ],
      "explanation": "...",
      "quality_score": 0.8
    }}
  ]
}}

Error types: SYNTAX_ERRORS, TYPE_ERRORS, LOGIC_ERRORS, LOOP_ERRORS, FUNCTION_ERRORS, COLLECTION_ERRORS, OOP_ERRORS, SCOPE_MISUNDERSTANDING, OFF_BY_ONE_ERROR, TYPE_MISMATCH, INDEX_OUT_OF_BOUNDS, NULL_POINTER_DEREFERENCE"""
        
        user_prompt = f"""Generate {count} distinct {diff_desc}-level MCQs about **{topic_focus}** in {lang_name}.

Rules:
- Each question tests ONE concept clearly
- Vary question types: code output, behavior, theory, syntax
- 4 options per question, exactly 1 correct
- Wrong answers map to error_type
- Include code_snippet for output/behavior questions
- Brief explanation for correct answer
- Avoid: "None/All of the above", trivial questions
- quality_score: self-assess 0.0-1.0

IMPORTANT: Make each question UNIQUE - no duplicates or near-duplicates."""
        
        return system_prompt, user_prompt
    
    def _parse_batch_response(self, raw_text: str, expected_count: int) -> Dict:
        """
        Parse and validate batch JSON response.
        """
        try:
            data = json.loads(raw_text.strip())
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON response: {e}")
        
        if 'questions' not in data or not isinstance(data['questions'], list):
            raise ValueError("Response missing 'questions' array")
        
        # Validate each question structure
        for idx, q in enumerate(data['questions']):
            if not all(k in q for k in ['question_text', 'options', 'explanation']):
                raise ValueError(f"Question {idx+1} missing required fields")
            
            if len(q['options']) != 4:
                raise ValueError(f"Question {idx+1} must have 4 options")
            
            correct_count = sum(1 for opt in q['options'] if opt.get('is_correct'))
            if correct_count != 1:
                raise ValueError(f"Question {idx+1} must have exactly 1 correct answer")
        
        if len(data['questions']) < expected_count * 0.7:  # Accept 70%+ yield
            print(f"⚠️ Expected {expected_count} questions, got {len(data['questions'])}")
        
        return data
