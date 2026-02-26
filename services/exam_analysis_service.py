"""
Exam Analysis Service - LLM-powered personalized feedback.
Uses OpenAI GPT-4o-mini to generate actionable study recommendations.
"""
import openai
from typing import List, Dict
import os
import logging
import json
import re
from urllib.parse import quote_plus

logger = logging.getLogger(__name__)


class ExamAnalysisService:
    """Generate exam feedback using OpenAI GPT-4o-mini"""
    
    def __init__(self):
        self.client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"), max_retries=1)
        self.model = "gpt-4o-mini"
        self.last_recommendations_source = "unknown"
        self.last_error_explanations_source = "unknown"
        
    def generate_feedback(
        self,
        topic_name: str,
        accuracy: float,
        fluency_ratio: float,
        current_mastery: float,
        error_summary: Dict[str, int],
        topic_breakdown: Dict[str, float],
        results: List,
        language_id: str = None,
        experience_level: str = None,
        error_history: Dict[str, int] = None,
        code_contexts: List[Dict] = None,
        prerequisite_status: Dict[str, float] = None
    ) -> List[str]:
        """
        Generate max 5 bullet points of actionable, context-aware feedback.
        
        Args:
            topic_name: Major topic ID (e.g., "PY_COND_01")
            accuracy: Overall score (0.0-1.0)
            fluency_ratio: Speed efficiency (1.0 = on pace)
            current_mastery: Current mastery level (0.0-1.0)
            error_summary: {error_type: count}
            topic_breakdown: {sub_topic: accuracy}
            results: Question results list
            language_id: Language (python_3, javascript_es6, etc.)
            experience_level: Student level (beginner, intermediate, advanced)
            error_history: Total error counts across all sessions
            code_contexts: Wrong answer code/explanations
            prerequisite_status: {prereq_id: current_mastery}
        
        Returns: 
            List of 5 bullet points (max 15 words each)
        """
        
        prompt = self._build_prompt(
            topic_name, accuracy, fluency_ratio, 
            current_mastery, error_summary, topic_breakdown,
            language_id, experience_level, error_history,
            code_contexts, prerequisite_status
        )
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a programming tutor providing concise, actionable exam feedback. Return EXACTLY 5 bullet points (max 15 words each). Be specific about errors and encouraging."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                temperature=0.3,  # Consistent, factual
                max_tokens=200,   # Short feedback
                timeout=10        # Fast response
            )
            
            bullets = self._parse_bullets(response.choices[0].message.content)
            return bullets[:5]  # Ensure max 5
            
        except Exception as e:
            logger.error(f"OpenAI analysis failed: {e}")
            return self._fallback_analysis(error_summary, topic_breakdown)
    
    def _build_prompt(
        self,
        topic_name: str,
        accuracy: float,
        fluency_ratio: float,
        current_mastery: float,
        error_summary: Dict[str, int],
        topic_breakdown: Dict[str, float],
        language_id: str = None,
        experience_level: str = None,
        error_history: Dict[str, int] = None,
        code_contexts: List[Dict] = None,
        prerequisite_status: Dict[str, float] = None
    ) -> str:
        """Build comprehensive, context-aware prompt for GPT-4o-mini"""
        
        # Language name mapping
        lang_names = {
            'python_3': 'Python 3',
            'javascript_es6': 'JavaScript (ES6)',
            'java_17': 'Java 17',
            'cpp_20': 'C++20',
            'go_1_21': 'Go 1.21'
        }
        language_name = lang_names.get(language_id, language_id) if language_id else "programming"
        
        # Experience level description
        level_desc = {
            'beginner': 'new to programming (just learning basics)',
            'intermediate': 'familiar with fundamentals',
            'advanced': 'experienced programmer'
        }
        student_level = level_desc.get(experience_level, 'intermediate') if experience_level else 'intermediate'
        
        # Build error summary
        if error_summary:
            error_text = "\n".join([
                f"- {error_type.replace('_', ' ').title()}: {count}x this session"
                for error_type, count in sorted(error_summary.items(), key=lambda x: -x[1])
            ])
        else:
            error_text = "None - all answers correct!"
        
        # Build error history section
        error_history_text = ""
        if error_history:
            error_history_text = "**ERROR HISTORY (across all sessions):**\n"
            for error_type, total_count in sorted(error_history.items(), key=lambda x: -x[1]):
                current_count = error_summary.get(error_type, 0) if error_summary else 0
                if total_count > current_count:
                    trend = "persistent" if total_count >= 4 else "improving"
                    error_history_text += f"- {error_type}: {total_count} total ({trend})\n"
                elif total_count == 1:
                    error_history_text += f"- {error_type}: first occurrence ⚡\n"
            error_history_text += "\n"
        
        # Build prerequisite status section
        prereq_text = ""
        if prerequisite_status:
            weak_prereqs = {k: v for k, v in prerequisite_status.items() if v < 0.65}
            if weak_prereqs:
                prereq_text = "**PREREQUISITE GAPS DETECTED:**\n"
                for prereq_id, mastery in weak_prereqs.items():
                    gap = 0.65 - mastery
                    prereq_text += f"- {prereq_id}: {mastery:.2f} (needs 0.65) — GAP: {gap:.2f} ⚠️\n"
                prereq_text += "→ Weak prerequisites may be causing current struggles.\n\n"
        
        # Build code context examples
        code_examples = ""
        if code_contexts:
            code_examples = "**WRONG ANSWERS WITH CONTEXT:**\n"
            for i, ctx in enumerate(code_contexts[:3], 1):  # Show top 3
                code_examples += f"\nQ{i}: {ctx.get('question', '')[:80]}...\n"
                if ctx.get('code_snippet'):
                    lang_short = language_id.split('_')[0] if language_id else 'code'
                    code_examples += f"```{lang_short}\n{ctx['code_snippet'][:150]}\n```\n"
                code_examples += f"  Student chose: \"{ctx.get('selected_answer', '')[:60]}\" ({ctx.get('error_type', 'ERROR')})\n"
                code_examples += f"  Correct: \"{ctx.get('correct_answer', '')[:60]}\"\n"
                if ctx.get('why_wrong'):
                    code_examples += f"  Why wrong: {ctx['why_wrong'][:100]}\n"
            code_examples += "\n"
        
        # Build topic performance
        topic_text = "\n".join([
            f"- {topic}: {acc*100:.0f}% correct"
            for topic, acc in topic_breakdown.items()
        ])
        
        # Speed assessment
        if fluency_ratio > 1.2:
            speed = "Fast (ahead of pace)"
        elif fluency_ratio < 0.8:
            speed = "Slow (needs more speed practice)"
        else:
            speed = "On pace"
        
        return f"""You are a programming tutor analyzing a student's exam. Generate EXACTLY 5 concise, **actionable** bullet points (max 15 words each).

**STUDENT PROFILE:**
- Language: {language_name}
- Experience Level: {student_level}
- Current Topic Mastery: {current_mastery:.2f}/1.0

**THIS SESSION:**
- Topic: {topic_name}
- Score: {accuracy*100:.0f}%
- Speed: {speed}

**ERRORS DETECTED THIS SESSION:**
{error_text}

{error_history_text}{prereq_text}**PERFORMANCE BY SUB-TOPIC:**
{topic_text}

{code_examples}**IMPORTANT — Tailor advice based on:**
1. **Language specifics**: Use {language_name}-specific syntax/idioms in explanations
2. **Experience level**: Adjust depth for {student_level} students
3. **Error patterns**: If persistent (4+ occurrences), diagnose root cause (check prerequisites)
4. **Code context**: Reference specific mistakes from wrong answers above

**FORMAT YOUR RESPONSE:**
1. Positive reinforcement (what they did well)
2. Primary weakness (specific, use error types and code context)
3-5. Actionable next steps (CONCRETE: "Review X", "Practice Y problems", "Focus on Z pattern")

Keep each bullet under 15 words. Be {student_level}-appropriate and {language_name}-specific."""
    
    def _parse_bullets(self, text: str) -> List[str]:
        """Extract bullet points from GPT response"""
        lines = text.strip().split('\n')
        bullets = []
        
        for line in lines:
            line = line.strip()
            
            # Remove bullet markers (-, *, •, numbers)
            if line.startswith(('-', '*', '•', '+')):
                line = line[1:].strip()
            elif line and len(line) > 0 and line[0].isdigit():
                # Remove "1. ", "2. " etc
                if '. ' in line[:4]:
                    line = line.split('. ', 1)[1].strip()
            
            if line and len(line) > 10:  # Ignore very short lines
                bullets.append(line)
        
        return bullets
    
    def _fallback_analysis(
        self, 
        error_summary: Dict[str, int],
        topic_breakdown: Dict[str, float]
    ) -> List[str]:
        """
        Rule-based fallback if OpenAI fails.
        Returns basic insights from error taxonomy.
        """
        bullets = []
        
        # Find best topic
        if topic_breakdown:
            best_topic = max(topic_breakdown.items(), key=lambda x: x[1])
            if best_topic[1] == 1.0:
                bullets.append(f"Perfect score on {best_topic[0]}!")
            elif best_topic[1] >= 0.8:
                bullets.append(f"Strong performance on {best_topic[0]} ({best_topic[1]*100:.0f}%)")
        
        # Find worst errors
        if error_summary:
            most_common = max(error_summary.items(), key=lambda x: x[1])
            error_name = most_common[0].replace('_', ' ').lower()
            bullets.append(f"Focus on {error_name} - occurred {most_common[1]} times")
            bullets.append(f"Review fundamentals related to {error_name}")
        else:
            bullets.append("No errors detected - excellent work!")
        
        # Generic advice
        bullets.append("Practice similar problems to reinforce concepts")
        
        # Pad to 5 if needed
        while len(bullets) < 5:
            bullets.append("Keep up the consistent practice")
        
        return bullets[:5]

    def generate_resource_recommendations(
        self,
        topic_name: str,
        error_summary: Dict[str, int],
        topic_breakdown: Dict[str, float],
        language_id: str = None,
        experience_level: str = None,
        error_history: Dict[str, int] = None,
        prerequisite_gaps: List[Dict] = None
    ) -> List[Dict[str, str]]:
        """
        Generate 3-5 resource recommendations as structured JSON.
        Returns [{"title": "...", "description": "...", "type": "...", "priority": ...}, ...]
        """
        prompt = self._build_resource_prompt(
            topic_name, error_summary, topic_breakdown,
            language_id, experience_level, error_history, prerequisite_gaps
        )

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "Return ONLY valid JSON object with this shape: {\"recommendations\": [ ... ]}. Each recommendation must include: type, priority, title, description, estimated_time_minutes, targets_error, prerequisite_addressed, language, action, focus_area, learning_goal, resource_url."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                temperature=0.4,
                max_tokens=420,
                timeout=20
            )

            content = response.choices[0].message.content or ""
            try:
                parsed = self._parse_json_list(content)
            except Exception:
                parsed = self._parse_text_recommendations(content)
            self.last_recommendations_source = "llm"
            return self._enrich_recommendations(parsed[:5], topic_name, language_id, error_summary)

        except Exception as e:
            logger.error(f"OpenAI resource recommendations failed: {e}")

            # One repair attempt: transform any free-form output into strict JSON object.
            try:
                repair_response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {
                            "role": "system",
                            "content": "Convert input into a strict JSON object with key 'recommendations' containing 3-5 recommendation objects. Return JSON only."
                        },
                        {
                            "role": "user",
                            "content": prompt
                        }
                    ],
                    temperature=0.2,
                    max_tokens=420,
                    timeout=20
                )

                repaired_content = repair_response.choices[0].message.content or ""
                try:
                    parsed = self._parse_json_list(repaired_content)
                except Exception:
                    parsed = self._parse_text_recommendations(repaired_content)
                self.last_recommendations_source = "llm"
                return self._enrich_recommendations(parsed[:5], topic_name, language_id, error_summary)
            except Exception as repair_error:
                logger.error(f"OpenAI resource recommendations repair failed: {repair_error}")
                self.last_recommendations_source = "fallback"
                return self._fallback_resources(topic_name, language_id, error_summary)

    def _build_resource_prompt(
        self,
        topic_name: str,
        error_summary: Dict[str, int],
        topic_breakdown: Dict[str, float],
        language_id: str = None,
        experience_level: str = None,
        error_history: Dict[str, int] = None,
        prerequisite_gaps: List[Dict] = None
    ) -> str:
        """Build prompt for structured resource recommendations with context."""
        
        lang_names = {
            'python_3': 'Python', 'javascript_es6': 'JavaScript',
            'java_17': 'Java', 'cpp_20': 'C++', 'go_1_21': 'Go'
        }
        language_name = lang_names.get(language_id, language_id) if language_id else "programming"
        
        # Identify most critical errors
        if error_summary:
            top_errors = sorted(error_summary.items(), key=lambda x: -x[1])[:3]
            error_text = "\n".join([f"- {err}: {cnt}x" for err, cnt in top_errors])
        else:
            error_text = "None"
        
        # Prerequisite gaps
        prereq_text = ""
        if prerequisite_gaps:
            prereq_text = "**PREREQUISITE GAPS:**\n"
            for gap in prerequisite_gaps:
                prereq_text += f"- {gap.get('topic', 'Unknown')}: {gap.get('current', 0):.2f} (needs {gap.get('required', 0.65):.2f})\n"
        
        exp_level = experience_level or 'intermediate'
        lang_id = language_id or 'unknown'
        
        return f"""Generate 3-5 prioritized learning recommendations for a {exp_level} {language_name} student.

**CONTEXT:**
- Current topic: {topic_name}
- Main errors: {error_text}
{prereq_text}

**RETURN FORMAT (strict JSON object):**
- Return a JSON object with a top-level key named `recommendations`
- `recommendations` must be an array of 3-5 objects
- Each object must include:
  - type (PREREQUISITE_REVIEW | DRILL | INTERACTIVE_TUTORIAL | EXTERNAL_RESOURCE | NEXT_TOPIC)
  - priority (integer 1-5)
  - title (string)
  - description (string)
  - estimated_time_minutes (integer)
  - targets_error (string or null)
  - prerequisite_addressed (string or null)
  - language (must be `{lang_id}`)
  - action (Start Practice | Review Topic | Read Guide | Try Tutorial)
  - focus_area (string)
  - learning_goal (string)
  - resource_url (string URL)

**RECOMMENDATION TYPES:**
- **PREREQUISITE_REVIEW** (priority 1): If gaps detected, suggest reviewing foundational topic first
- **DRILL** (priority 2): Focused practice on specific error patterns (10-15 targeted questions)
- **INTERACTIVE_TUTORIAL** (priority 3): Step-by-step guided learning
- **EXTERNAL_RESOURCE** (priority 4): Specific {language_name} documentation/guides
- **NEXT_TOPIC** (priority 5): Natural progression suggestions

**IMPORTANT:**
- Make recommendations **specific to {language_name}** (e.g., "Python list comprehension drill" not "array manipulation")
- Prioritize prerequisite gaps highest
- For persistent errors (4+ occurrences), recommend drills
- Keep descriptions focused on HOW this fixes their specific problems
- resource_url must be practical and usable by students"""

    def _parse_json_list(self, text: str) -> List[Dict[str, str]]:
        """Parse recommendation list from model response (array or wrapped object)."""
        cleaned = text.strip()

        # Strip fenced markdown blocks like ```json ... ```
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            if len(lines) >= 2:
                # Remove first fence line and trailing fence if present
                lines = lines[1:]
                if lines and lines[-1].strip().startswith("```"):
                    lines = lines[:-1]
                cleaned = "\n".join(lines).strip()

        data = None

        # 1) Try direct JSON parse first
        try:
            data = json.loads(cleaned)
        except Exception:
            data = None

        # 2) If direct parse fails, try extracting array or object substrings
        if data is None:
            arr_start = cleaned.find("[")
            arr_end = cleaned.rfind("]")
            if arr_start != -1 and arr_end != -1 and arr_end > arr_start:
                try:
                    data = json.loads(cleaned[arr_start:arr_end + 1])
                except Exception:
                    data = None

        if data is None:
            obj_start = cleaned.find("{")
            obj_end = cleaned.rfind("}")
            if obj_start != -1 and obj_end != -1 and obj_end > obj_start:
                try:
                    data = json.loads(cleaned[obj_start:obj_end + 1])
                except Exception:
                    data = None

        if data is None:
            raise ValueError("No parseable JSON found")

        # Accept either a raw array or common object wrappers
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            items = None
            for key in ["recommendations", "resources", "items", "data"]:
                if isinstance(data.get(key), list):
                    items = data[key]
                    break
            if items is None:
                raise ValueError("No recommendation list found in JSON object")
        else:
            raise ValueError("Unexpected JSON type")

        results = []
        for item in items:
            if not isinstance(item, dict):
                continue

            # Phase 2 Fix (Bug 1): Keep ALL fields from LLM response, not just title/description
            title = str(item.get("title", "")).strip()
            description = str(item.get("description", "")).strip()
            if title and description:
                results.append(item)

        if not results:
            raise ValueError("Parsed JSON but found no valid recommendation items")

        return results

    def _parse_text_recommendations(self, text: str) -> List[Dict[str, str]]:
        """Best-effort parser for non-JSON recommendation output."""
        cleaned = text.strip()
        lines = [ln.strip() for ln in cleaned.splitlines() if ln.strip()]

        # 0) Extract from malformed JSON-like fragments first (common failure mode)
        # Example fragments: "title": "...", "description": "..."
        pair_matches = re.findall(
            r'"title"\s*:\s*"([^"]{3,160})"[\s\S]{0,500}?"description"\s*:\s*"([^"]{10,500})"',
            cleaned,
            flags=re.IGNORECASE
        )
        if pair_matches:
            items = []
            for title, description in pair_matches[:5]:
                title_clean = re.sub(r'\s+', ' ', title).strip(' ,;:-"')
                desc_clean = re.sub(r'\s+', ' ', description).strip(' ,;:-"')
                if title_clean and desc_clean:
                    items.append({"title": title_clean, "description": desc_clean})
            if items:
                return items

        def is_json_fragment(line: str) -> bool:
            stripped = line.strip()
            if not stripped:
                return True
            json_key_like = re.match(r'^"[A-Za-z0-9_]+"\s*:\s*', stripped) is not None
            has_json_tokens = any(tok in stripped for tok in ['{', '}', '[', ']', '":', ',"', '},', '],'])
            return json_key_like or has_json_tokens

        # Remove markdown bullets/numbering for extraction
        normalized = [re.sub(r'^([\-*•]|\d+[\).])\s*', '', ln).strip() for ln in lines]

        items: List[Dict[str, str]] = []
        i = 0
        while i < len(normalized):
            line = normalized[i]

            # Candidate title lines are concise and non-empty
            if 3 <= len(line) <= 90 and not is_json_fragment(line):
                title = line
                description_parts = []
                j = i + 1
                while j < len(normalized):
                    nxt = normalized[j]
                    if is_json_fragment(nxt):
                        break
                    # stop at next likely heading/title-like bullet
                    if re.match(r'^(Recommendation|Title|Focus|Goal)\b', nxt, re.IGNORECASE):
                        break
                    if re.match(r'^[A-Z][A-Za-z0-9\s\-]{3,80}$', nxt) and len(description_parts) > 0:
                        break
                    description_parts.append(nxt)
                    if len(' '.join(description_parts)) > 220:
                        break
                    j += 1

                description = ' '.join(description_parts).strip()
                if title and description:
                    items.append({"title": title, "description": description})
                i = max(j, i + 1)
            else:
                i += 1

        # Keep up to 5, ensure at least one parsed item
        items = [it for it in items if it.get("title") and it.get("description")][:5]
        if items:
            return items

        # 3) Final fallback: convert informative prose lines into recommendations
        prose_lines = []
        for ln in normalized:
            if is_json_fragment(ln):
                continue
            if len(ln) < 18:
                continue
            prose_lines.append(ln)

        if prose_lines:
            synthesized = []
            for idx, ln in enumerate(prose_lines[:5], 1):
                # Use first clause as title and full line as description
                title = ln.split(':', 1)[0].split('.', 1)[0].strip()
                if len(title) < 5:
                    title = f"Recommendation {idx}"
                if len(title) > 70:
                    title = title[:67].rstrip() + "..."
                synthesized.append({
                    "title": title,
                    "description": ln
                })
            if synthesized:
                return synthesized

        if not items:
            raise ValueError("No parseable recommendations found in text output")
        return items

    def _enrich_recommendations(
        self,
        recommendations: List[Dict],
        topic_name: str,
        language_id: str = None,
        error_summary: Dict[str, int] = None
    ) -> List[Dict]:
        """Ensure recommendations have actionable fields and online resource links."""
        enriched = []
        top_error = None
        if error_summary:
            top_error = max(error_summary.items(), key=lambda x: x[1])[0]

        for rec in recommendations:
            rec_type = rec.get("type") or "CONCEPTUAL_REVIEW"
            target_error = rec.get("targets_error") or top_error
            title = str(rec.get("title", "Study Plan")).strip()

            rec["type"] = rec_type
            rec["priority"] = int(rec.get("priority", 3))
            rec["estimated_time_minutes"] = int(rec.get("estimated_time_minutes", 30))
            rec["language"] = rec.get("language") or language_id
            rec["targets_error"] = target_error
            rec["action"] = rec.get("action") or ("Start Practice" if rec_type == "DRILL" else "Review Topic")
            rec["focus_area"] = rec.get("focus_area") or f"{topic_name} - {str(target_error).replace('_', ' ').title() if target_error else 'Core Concepts'}"
            rec["learning_goal"] = rec.get("learning_goal") or f"Fix {str(target_error).replace('_', ' ').lower() if target_error else 'key mistakes'} and improve consistency"

            if not rec.get("resource_url"):
                rec["resource_url"] = self._build_resource_link(
                    language_id=language_id,
                    topic_name=topic_name,
                    title=title,
                    target_error=target_error,
                    rec_type=rec_type
                )

            enriched.append(rec)

        return enriched

    def _parse_error_explanations_text(
        self,
        content: str,
        error_types: List[str]
    ) -> Dict[str, Dict[str, str]]:
        """
        Extract error explanations from malformed JSON or plain text.
        Looks for error type patterns and associated fields.
        """
        explanations = {}
        
        # Strategy 1: Try to extract JSON-like blocks per error type
        for error_type in error_types:
            if not error_type:
                continue
            
            # Look for error type as a key
            pattern = rf'"{error_type}":\s*\{{([^}}]+)\}}'
            match = re.search(pattern, content, re.DOTALL)
            
            if match:
                block = match.group(1)
                explanation = {}
                
                # Extract fields
                for field in ['why_wrong', 'correct_approach', 'language_tip', 'practice_suggestion']:
                    field_pattern = rf'"{field}":\s*"([^"]*)"'
                    field_match = re.search(field_pattern, block)
                    if field_match:
                        explanation[field] = field_match.group(1).strip()
                
                if explanation:
                    explanations[error_type] = explanation
        
        # Strategy 2: Look for labeled sections in text
        if not explanations:
            lines = content.split('\n')
            current_error = None
            current_explanation = {"why_wrong": "", "correct_approach": "", "language_tip": "", "practice_suggestion": ""}
            
            for line in lines:
                line = line.strip()
                
                # Check if line contains an error type
                for error_type in error_types:
                    if error_type in line:
                        if current_error and any(current_explanation.values()):
                            explanations[current_error] = current_explanation.copy()
                        current_error = error_type
                        current_explanation = {"why_wrong": "", "correct_approach": "", "language_tip": "", "practice_suggestion": ""}
                        break
                
                # Extract field values
                if current_error:
                    if 'why_wrong' in line.lower() or 'why wrong' in line.lower():
                        text = re.sub(r'^[^:]*:\s*', '', line)
                        current_explanation['why_wrong'] = text.strip('" ')
                    elif 'correct_approach' in line.lower() or 'correct approach' in line.lower() or 'how to fix' in line.lower():
                        text = re.sub(r'^[^:]*:\s*', '', line)
                        current_explanation['correct_approach'] = text.strip('" ')
                    elif 'language_tip' in line.lower() or 'language tip' in line.lower() or 'key concept' in line.lower():
                        text = re.sub(r'^[^:]*:\s*', '', line)
                        current_explanation['language_tip'] = text.strip('" ')
                    elif 'practice' in line.lower():
                        text = re.sub(r'^[^:]*:\s*', '', line)
                        current_explanation['practice_suggestion'] = text.strip('" ')
            
            # Add last error
            if current_error and any(current_explanation.values()):
                explanations[current_error] = current_explanation
        
        return explanations

    def _build_resource_link(
        self,
        language_id: str,
        topic_name: str,
        title: str,
        target_error: str = None,
        rec_type: str = None
    ) -> str:
        """Generate a practical, stable online resource URL for a recommendation."""
        
        # Primary documentation and tutorial resources
        primary_resources = {
            "python_3": {
                "default": "https://docs.python.org/3/tutorial/",
                "syntax": "https://docs.python.org/3/tutorial/introduction.html",
                "logic": "https://docs.python.org/3/tutorial/controlflow.html",
                "function": "https://docs.python.org/3/tutorial/controlflow.html#defining-functions",
                "loop": "https://docs.python.org/3/tutorial/controlflow.html#for-statements",
                "variable": "https://docs.python.org/3/tutorial/introduction.html#using-python-as-a-calculator",
                "conditional": "https://docs.python.org/3/tutorial/controlflow.html#if-statements",
                "collection": "https://docs.python.org/3/tutorial/datastructures.html",
                "oop": "https://docs.python.org/3/tutorial/classes.html"
            },
            "javascript_es6": {
                "default": "https://developer.mozilla.org/en-US/docs/Web/JavaScript/Guide",
                "syntax": "https://developer.mozilla.org/en-US/docs/Web/JavaScript/Guide/Grammar_and_types",
                "logic": "https://developer.mozilla.org/en-US/docs/Web/JavaScript/Guide/Control_flow_and_error_handling",
                "function": "https://developer.mozilla.org/en-US/docs/Web/JavaScript/Guide/Functions",
                "loop": "https://developer.mozilla.org/en-US/docs/Web/JavaScript/Guide/Loops_and_iteration",
                "variable": "https://developer.mozilla.org/en-US/docs/Web/JavaScript/Guide/Grammar_and_types#declarations",
                "conditional": "https://developer.mozilla.org/en-US/docs/Web/JavaScript/Guide/Control_flow_and_error_handling#conditional_statements",
                "collection": "https://developer.mozilla.org/en-US/docs/Web/JavaScript/Guide/Indexed_collections",
                "oop": "https://developer.mozilla.org/en-US/docs/Web/JavaScript/Guide/Working_with_Objects"
            },
            "java_17": {
                "default": "https://dev.java/learn/",
                "syntax": "https://dev.java/learn/language-basics/",
                "logic": "https://dev.java/learn/language-basics/control-flow/",
                "function": "https://dev.java/learn/language-basics/methods/",
                "loop": "https://dev.java/learn/language-basics/control-flow/",
                "variable": "https://dev.java/learn/language-basics/variables/",
                "conditional": "https://dev.java/learn/language-basics/control-flow/",
                "collection": "https://dev.java/learn/api/collections-framework/",
                "oop": "https://dev.java/learn/oop/"
            },
            "cpp_20": {
                "default": "https://en.cppreference.com/w/cpp",
                "syntax": "https://en.cppreference.com/w/cpp/language/basic_concepts",
                "logic": "https://en.cppreference.com/w/cpp/language/statements",
                "function": "https://en.cppreference.com/w/cpp/language/functions",
                "loop": "https://en.cppreference.com/w/cpp/language/for",
                "variable": "https://en.cppreference.com/w/cpp/language/declarations",
                "conditional": "https://en.cppreference.com/w/cpp/language/if",
                "collection": "https://en.cppreference.com/w/cpp/container",
                "oop": "https://en.cppreference.com/w/cpp/language/classes"
            },
            "go_1_21": {
                "default": "https://go.dev/tour/welcome/1",
                "syntax": "https://go.dev/tour/basics/1",
                "logic": "https://go.dev/tour/flowcontrol/1",
                "function": "https://go.dev/tour/basics/4",
                "loop": "https://go.dev/tour/flowcontrol/1",
                "variable": "https://go.dev/tour/basics/8",
                "conditional": "https://go.dev/tour/flowcontrol/5",
                "collection": "https://go.dev/tour/moretypes/1",
                "oop": "https://go.dev/tour/methods/1"
            }
        }
        
        # Detect topic category from title and error type
        topic_lower = (title + " " + (target_error or "") + " " + topic_name).lower()
        
        category = "default"
        if any(word in topic_lower for word in ["syntax", "basic", "fundamental"]):
            category = "syntax"
        elif any(word in topic_lower for word in ["logic", "logical", "control flow"]):
            category = "logic"
        elif any(word in topic_lower for word in ["function", "method", "procedure"]):
            category = "function"
        elif any(word in topic_lower for word in ["loop", "iteration", "for", "while"]):
            category = "loop"
        elif any(word in topic_lower for word in ["variable", "declaration", "assignment"]):
            category = "variable"
        elif any(word in topic_lower for word in ["condition", "if", "else", "switch"]):
            category = "conditional"
        elif any(word in topic_lower for word in ["array", "list", "collection", "data structure"]):
            category = "collection"
        elif any(word in topic_lower for word in ["oop", "object", "class", "inheritance"]):
            category = "oop"
        
        # Get language-specific resource
        if language_id in primary_resources:
            lang_resources = primary_resources[language_id]
            return lang_resources.get(category, lang_resources["default"])
        
        # Fallback to curated learning platforms
        query = quote_plus(f"{language_id} {topic_name} {title}")
        return f"https://www.w3schools.com/search/search.asp?q={query}"

    def _fallback_resources(
        self,
        topic_name: str,
        language_id: str = None,
        error_summary: Dict[str, int] = None
    ) -> List[Dict[str, str]]:
        """Context-aware fallback recommendations if LLM fails."""
        top_error = None
        if error_summary:
            top_error = max(error_summary.items(), key=lambda x: x[1])[0]
        readable_error = top_error.replace("_", " ").title() if top_error else "Core Concepts"

        base = [
            {
                "type": "CONCEPTUAL_REVIEW",
                "priority": 1,
                "title": f"{topic_name} Foundations Review",
                "description": f"Rebuild your understanding of {topic_name} before advanced exercises.",
                "estimated_time_minutes": 30,
                "targets_error": top_error,
                "prerequisite_addressed": None,
                "language": language_id,
                "action": "Read Guide",
                "focus_area": f"{topic_name} core rules",
                "learning_goal": "Explain key rules and apply them correctly",
                "resource_url": self._build_resource_link(language_id, topic_name, f"{topic_name} basics", top_error, "EXTERNAL_RESOURCE")
            },
            {
                "type": "DRILL",
                "priority": 2,
                "title": f"{readable_error} Targeted Drill",
                "description": f"Practice 12 focused questions that specifically target {readable_error.lower()}.",
                "estimated_time_minutes": 25,
                "targets_error": top_error,
                "prerequisite_addressed": None,
                "language": language_id,
                "action": "Start Practice",
                "focus_area": readable_error,
                "learning_goal": f"Reduce {readable_error.lower()} mistakes by applying a repeatable checklist",
                "resource_url": self._build_resource_link(language_id, topic_name, f"{readable_error} practice", top_error, "DRILL")
            },
            {
                "type": "EXTERNAL_RESOURCE",
                "priority": 3,
                "title": "Official Documentation Walkthrough",
                "description": "Use official docs examples and reproduce them line-by-line with small variations.",
                "estimated_time_minutes": 20,
                "targets_error": top_error,
                "prerequisite_addressed": None,
                "language": language_id,
                "action": "Read Guide",
                "focus_area": "Language syntax and idioms",
                "learning_goal": "Translate docs examples into your own solutions",
                "resource_url": self._build_resource_link(language_id, topic_name, "official documentation", top_error, "EXTERNAL_RESOURCE")
            }
        ]
        return base
    
    def generate_error_explanations(
        self,
        errors: List[Dict],
        language_id: str,
        experience_level: str
    ) -> Dict[str, Dict[str, str]]:
        """
        Generate detailed, language-specific explanations for each error type.
        
        Args:
            errors: List of error dicts with error_type, count, code_context, option_explanation
            language_id: Language (python_3, javascript_es6, etc.)
            experience_level: Student level (beginner, intermediate, advanced)
        
        Returns:
            {
                "OFF_BY_ONE_ERROR": {
                    "why_wrong": "In Python, range(5) produces 0-4, not 1-5",
                    "correct_approach": "Use range(len(arr)) for valid indices",
                    "language_tip": "Python uses 0-indexing; len(arr)=5 means indices 0-4",
                    "practice_suggestion": "Practice range() and indexing problems"
                },
                ...
            }
        """
        
        if not errors:
            return {}
        
        lang_names = {
            'python_3': 'Python', 'javascript_es6': 'JavaScript',
            'java_17': 'Java', 'cpp_20': 'C++', 'go_1_21': 'Go'
        }
        language_name = lang_names.get(language_id, language_id)
        
        # Build compact error context
        error_details = []
        for err in errors[:3]:  # Max 3 errors for lower latency
            detail = f"**{err.get('error_type', 'UNKNOWN')}** ({err.get('count', 1)}x):\n"
            if err.get('code_context'):
                detail += f"  Code: {err['code_context'][:90]}\n"
            if err.get('option_explanation'):
                detail += f"  What happened: {err['option_explanation'][:90]}\n"
            error_details.append(detail)
        
        prompt = f"""You are teaching a {experience_level} {language_name} programmer. For each error below, provide a **{language_name}-specific** explanation.

{chr(10).join(error_details)}

**Return valid JSON:**
```json
{{
  "ERROR_TYPE": {{
    "why_wrong": "1-2 sentence explanation specific to {language_name} (use {language_name} terminology)",
    "correct_approach": "How to fix it ({language_name} syntax/idioms)",
    "language_tip": "Key {language_name} concept to understand",
    "practice_suggestion": "Specific type of problems to practice"
  }},
  ...
}}
```

**IMPORTANT:**
- Use {language_name} syntax in examples (e.g., Python: range(), JS: array.length, C++: vector.size())
- Adjust depth for {experience_level} level
- Be specific about WHY the mistake happens in {language_name}"""
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "Return ONLY valid JSON, no markdown."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.2,
                max_tokens=350,
                timeout=20
            )
            
            content = response.choices[0].message.content or ""
            # Strip code fences if present
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                content = content.strip("`").strip()
            
            # Try multiple parsing strategies
            try:
                # Strategy 1: Direct JSON parsing
                self.last_error_explanations_source = "llm"
                return json.loads(content.strip())
            except json.JSONDecodeError as json_err:
                logger.warning(f"Direct JSON parse failed: {json_err}, attempting text extraction...")
                # Strategy 2: Extract error blocks manually
                try:
                    explanations = self._parse_error_explanations_text(content, [e.get('error_type') for e in errors])
                    if explanations:
                        self.last_error_explanations_source = "llm"
                        return explanations
                except Exception as parse_err:
                    logger.warning(f"Text parsing failed: {parse_err}")
                raise json_err  # Re-raise to trigger fallback
            
        except Exception as e:
            logger.error(f"Error explanation generation failed: {e}")
            self.last_error_explanations_source = "fallback"
            # Fallback to basic explanations
            return self._fallback_error_explanations(errors)
    
    def _fallback_error_explanations(self, errors: List[Dict]) -> Dict[str, Dict[str, str]]:
        """Fallback explanations if LLM fails."""
        fallbacks = {}
        for err in errors:
            err_type = err.get('error_type', 'UNKNOWN')
            fallbacks[err_type] = {
                "why_wrong": f"{err_type.replace('_', ' ').title()} detected",
                "correct_approach": "Review the concept and try similar problems",
                "language_tip": "Check language documentation for correct syntax",
                "practice_suggestion": "Practice problems targeting this error type"
            }
        return fallbacks
