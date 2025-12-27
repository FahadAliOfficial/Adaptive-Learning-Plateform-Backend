"""
Gemini AI integration for MCQ generation.
Implements retry logic, rate limiting, and safety checks.

Loophole Fixes Implemented:
- #8: Prompt injection prevention (sanitize_topic)
- #9: Sub-topic drift prevention (explicit sub-topic control)
- #10: Empty option hallucination (quality validation + forbidden patterns)
- Retry logic with exponential backoff (handles API failures)
"""
import google.generativeai as genai
import json
import os
from typing import Dict, Optional, List
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from datetime import datetime, timezone
import re

from services.content_engine.validator import MultiLanguageValidator

# Configure Gemini
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))


class GeminiFactory:
    """
    Generates MCQ questions using Gemini 1.5 Pro.
    
    Features:
    - Automatic retry on failures (exponential backoff)
    - Prompt injection prevention
    - Multi-language support
    - Quality validation before storage
    - Sub-topic control for curriculum coverage
    """
    
    # Model configuration
    MODEL_NAME = "gemini-1.5-pro"
    TEMPERATURE = 0.7  # Balance creativity with consistency
    
    # Safety settings (prevent harmful content)
    SAFETY_SETTINGS = [
        {
            "category": "HARM_CATEGORY_HARASSMENT",
            "threshold": "BLOCK_MEDIUM_AND_ABOVE"
        },
        {
            "category": "HARM_CATEGORY_HATE_SPEECH",
            "threshold": "BLOCK_MEDIUM_AND_ABOVE"
        },
        {
            "category": "HARM_CATEGORY_SEXUALLY_EXPLICIT",
            "threshold": "BLOCK_MEDIUM_AND_ABOVE"
        },
        {
            "category": "HARM_CATEGORY_DANGEROUS_CONTENT",
            "threshold": "BLOCK_MEDIUM_AND_ABOVE"
        }
    ]
    
    def __init__(self):
        self.model = genai.GenerativeModel(
            model_name=self.MODEL_NAME,
            safety_settings=self.SAFETY_SETTINGS,
            generation_config={
                "temperature": self.TEMPERATURE,
                "top_p": 0.95,
                "top_k": 40,
                "max_output_tokens": 2048
            }
        )
    
    @staticmethod
    def sanitize_topic(topic: str) -> str:
        """
        Prevent prompt injection attacks.
        
        Loophole Fix #8: Blocks malicious prompts
        
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
            r'ignore.*(previous|all|any).*(instructions?|prompts?)',  # Allow words between
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
        Generate a single MCQ using Gemini AI.
        
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
        prompt = self._build_prompt(
            safe_topic, language_id, mapping_id, difficulty, sub_topic
        )
        
        # 3. Retry loop for quality validation
        max_quality_retries = 3
        for attempt in range(max_quality_retries):
            try:
                # 4. Call Gemini API (with auto-retry via @retry decorator)
                response = self.model.generate_content(prompt)
                
                # 5. Extract JSON from response
                raw_text = response.text
                question_data = self._parse_response(raw_text)
                
                # 6. Validate option quality (Loophole Fix #10)
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
    ) -> str:
        """
        Construct engineered prompt for Gemini.
        
        Loophole Fix #9: Explicit sub-topic control prevents drift
        Loophole Fix #10: FORBIDDEN list prevents lazy options
        """
        # Map language_id to human name
        lang_map = {
            "python_3": "Python 3",
            "javascript_es6": "JavaScript (ES6)",
            "java_17": "Java 17",
            "cpp_20": "C++20",
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
        
        prompt = f"""You are an expert computer science educator creating multiple-choice questions for students.

**Task:** Generate ONE high-quality MCQ about **{topic_desc}** in **{lang_name}** at **{diff_desc}** difficulty.

{subtopic_constraint}

**Requirements:**
1. Question must be clear and unambiguous
2. Choose the most effective format:
   - **Code-based**: Include a code snippet for output/behavior questions
   - **Conceptual**: Focus on understanding without code for theory/principles
   - **Scenario-based**: Describe a programming situation requiring concept application
3. Provide exactly 4 options (A, B, C, D) with ONE correct answer
4. Options should test understanding, not just memorization  
5. Include a brief explanation of the correct answer
6. If using code, it must be syntactically correct and runnable
7. Avoid trivial questions (e.g., "What keyword starts a loop?")

**ERROR PATTERN FOCUS:**
Design distractors that map to specific programming errors:
- SYNTAX_ERRORS: Missing semicolons, brace mismatches, indentation issues
- TYPE_ERRORS: Type mismatches, undefined variables, null pointers
- LOGIC_ERRORS: Wrong operators, boolean logic mistakes
- LOOP_ERRORS: Off-by-one, infinite loops, scope issues
- FUNCTION_ERRORS: Scope problems, missing returns, argument mismatches
- COLLECTION_ERRORS: Index bounds, key errors, modification during iteration
- OOP_ERRORS: Inheritance mistakes, encapsulation violations
- MEMORY_ERRORS: Memory leaks, dangling pointers (C++)

**FORBIDDEN OPTIONS (DO NOT USE):**
- ❌ "None of the above"
- ❌ "All of the above" 
- ❌ "I don't know"
- ❌ "Cannot determine"
- ❌ "The code will not compile" (unless specifically testing compilation errors)

**Distractor Quality:**
Each wrong answer (distractor) must be:
- Based on a specific error pattern from above categories
- Plausible enough that a beginner might choose it
- Clearly wrong to someone who understands the concept

**Difficulty Guidelines:**
- Beginner (0.0-0.3): Basic syntax, single concept
- Intermediate (0.3-0.7): Multiple concepts, logic required
- Advanced (0.7-1.0): Edge cases, performance, design patterns

**Output Format (STRICT JSON):**

**For Code-Based Questions:**
```json
{{
  "question_text": "What is the output of this code?",
  "code_snippet": "# Syntactically correct code here",
  "options": [
    {{"id": "A", "text": "Correct output", "is_correct": true, "error_type": null}},
    {{"id": "B", "text": "Off-by-one result", "is_correct": false, "error_type": "OFF_BY_ONE_ERROR"}},
    {{"id": "C", "text": "Wrong scope result", "is_correct": false, "error_type": "SCOPE_MISUNDERSTANDING"}},
    {{"id": "D", "text": "Type error result", "is_correct": false, "error_type": "TYPE_MISMATCH"}}
  ],
  "explanation": "Brief explanation of correct answer and common mistakes"
}}
```

**For Conceptual Questions:**
```json
{{
  "question_text": "Which statement about {lang_name} variables is correct?",
  "options": [
    {{"id": "A", "text": "Correct concept", "is_correct": true, "error_type": null}},
    {{"id": "B", "text": "Scope misconception", "is_correct": false, "error_type": "SCOPE_MISUNDERSTANDING"}},
    {{"id": "C", "text": "Type misconception", "is_correct": false, "error_type": "TYPE_MISMATCH"}},
    {{"id": "D", "text": "Language confusion", "is_correct": false, "error_type": "LANGUAGE_CONFUSION_ERROR"}}
  ],
  "explanation": "Brief explanation of the concept and why distractors are wrong"
}}
```
  "quality_assessment": {{
    "score": 0.85,
    "reasoning": "Question tests understanding with realistic distractors"
  }}
}}
```

**IMPORTANT:** Return ONLY the JSON. Do not include markdown code fences, explanations, or any text outside the JSON structure.
"""
        return prompt
    
    def _parse_response(self, raw_text: str) -> Dict:
        """
        Extract JSON from Gemini response.
        Handles cases where AI wraps JSON in markdown fences.
        """
        # Remove markdown code fences if present
        text = raw_text.strip()
        if text.startswith("```json"):
            text = text[7:]  # Remove ```json
        elif text.startswith("```"):
            text = text[3:]  # Remove ```
        
        if text.endswith("```"):
            text = text[:-3]  # Remove closing ```
        
        text = text.strip()
        
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
            data = json.loads(raw_text.strip().strip('`').replace('```json', '').replace('```', ''))
            if 'quality_assessment' in data and 'score' in data['quality_assessment']:
                score = float(data['quality_assessment']['score'])
                return max(0.0, min(1.0, score))  # Clamp to [0, 1]
        except Exception:
            pass
        
        return 0.5  # Default fallback
    
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
        Generate multiple questions (with deduplication).
        
        Args:
            count: Number of unique questions to generate
        
        Returns:
            List of question dictionaries (may be less than count if duplicates occur)
        """
        questions = []
        seen_hashes = set()
        attempts = 0
        max_attempts = count * 2  # Allow some retries for duplicates
        
        while len(questions) < count and attempts < max_attempts:
            attempts += 1
            
            try:
                q = self.generate_question(
                    topic, language_id, mapping_id, difficulty, sub_topic
                )
                
                # Check for duplicate (Loophole Fix #12)
                content_hash = MultiLanguageValidator.generate_content_hash(q)
                if content_hash not in seen_hashes:
                    q['content_hash'] = content_hash
                    questions.append(q)
                    seen_hashes.add(content_hash)
                else:
                    print(f"⚠️ Duplicate question generated (hash collision), retrying...")
            
            except Exception as e:
                print(f"⚠️ Question generation failed: {e}")
                # Continue trying (retries handled by @retry decorator)
        
        return questions
    
    def generate_batch_with_coverage(
        self,
        mapping_id: str,
        language_id: str,
        difficulty: float,
        count: int,
        curriculum_data: Dict
    ) -> List[Dict]:
        """
        Generate batch with guaranteed sub-topic coverage.
        
        Loophole Fix #9: Ensures even distribution across curriculum sub-topics
        
        Strategy:
        1. Get all sub-topics from curriculum
        2. Distribute questions evenly across sub-topics (round-robin)
        3. Generate with explicit sub-topic constraints
        """
        import math
        
        mapping_info = curriculum_data.get(mapping_id, {})
        sub_topics = mapping_info.get('sub_topics', [])
        
        if not sub_topics:
            # Fallback to regular batch generation
            return self.generate_batch(
                topic=mapping_info.get('name', mapping_id),
                language_id=language_id,
                mapping_id=mapping_id,
                difficulty=difficulty,
                count=count
            )
        
        # Calculate questions per sub-topic (round-robin)
        questions_per_subtopic = math.ceil(count / len(sub_topics))
        
        questions = []
        seen_hashes = set()
        
        # Generate evenly across sub-topics
        for subtopic in sub_topics:
            if len(questions) >= count:
                break
            
            for _ in range(questions_per_subtopic):
                if len(questions) >= count:
                    break
                
                try:
                    q = self.generate_question(
                        topic=mapping_info.get('name', mapping_id),
                        language_id=language_id,
                        mapping_id=mapping_id,
                        difficulty=difficulty,
                        sub_topic=subtopic  # ✅ Explicit sub-topic
                    )
                    
                    # Deduplicate
                    content_hash = MultiLanguageValidator.generate_content_hash(q)
                    if content_hash not in seen_hashes:
                        q['content_hash'] = content_hash
                        questions.append(q)
                        seen_hashes.add(content_hash)
                
                except Exception as e:
                    print(f"⚠️ Failed to generate for {subtopic}: {e}")
                    continue
        
        return questions
