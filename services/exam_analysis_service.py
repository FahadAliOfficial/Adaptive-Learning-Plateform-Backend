"""
Exam Analysis Service - LLM-powered personalized feedback.
Uses OpenAI GPT-4o-mini to generate actionable study recommendations.
"""
import openai
from typing import List, Dict
import os
import logging
import json

logger = logging.getLogger(__name__)


class ExamAnalysisService:
    """Generate exam feedback using OpenAI GPT-4o-mini"""
    
    def __init__(self):
        self.client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self.model = "gpt-4o-mini"
        
    def generate_feedback(
        self,
        topic_name: str,
        accuracy: float,
        fluency_ratio: float,
        current_mastery: float,
        error_summary: Dict[str, int],
        topic_breakdown: Dict[str, float],
        results: List
    ) -> List[str]:
        """
        Generate max 5 bullet points of actionable feedback.
        
        Args:
            topic_name: Major topic ID (e.g., "PY_COND_01")
            accuracy: Overall score (0.0-1.0)
            fluency_ratio: Speed efficiency (1.0 = on pace)
            current_mastery: Current mastery level (0.0-1.0)
            error_summary: {error_type: count}
            topic_breakdown: {sub_topic: accuracy}
            results: Question results list
        
        Returns: 
            List of 5 bullet points (max 15 words each)
        """
        
        prompt = self._build_prompt(
            topic_name, accuracy, fluency_ratio, 
            current_mastery, error_summary, topic_breakdown
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
        topic_breakdown: Dict[str, float]
    ) -> str:
        """Build focused prompt for GPT-4o-mini"""
        
        # Build error summary
        if error_summary:
            error_text = "\n".join([
                f"- {error_type.replace('_', ' ').title()}: {count} time(s)"
                for error_type, count in error_summary.items()
            ])
        else:
            error_text = "None - all answers correct!"
        
        # Build topic accuracy
        topic_text = "\n".join([
            f"- {topic}: {acc*100:.0f}% correct"
            for topic, acc in topic_breakdown.items()
        ])
        
        # Speed assessment
        if fluency_ratio > 1.2:
            speed = "Fast (ahead of pace)"
        elif fluency_ratio < 0.8:
            speed = "Slow (needs more practice for speed)"
        else:
            speed = "On pace"
        
        return f"""Analyze this programming exam and provide EXACTLY 5 short bullet points:

**EXAM:** {topic_name}
- Overall Score: {accuracy*100:.0f}%
- Speed: {speed}
- Current Mastery Level: {current_mastery:.2f}/1.0

**ERRORS DETECTED:**
{error_text}

**PERFORMANCE BY TOPIC:**
{topic_text}

**FORMAT YOUR RESPONSE AS:**
1. What they did well (positive reinforcement)
2. Main weakness (be specific, reference error types)
3-5. Concrete action items to improve (specific, actionable steps)

Keep each bullet under 15 words. Be encouraging but honest."""
    
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
        topic_breakdown: Dict[str, float]
    ) -> List[Dict[str, str]]:
        """
        Generate 3-5 resource recommendations as structured JSON.
        Returns [{"title": "...", "description": "..."}, ...]
        """
        prompt = self._build_resource_prompt(topic_name, error_summary, topic_breakdown)

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "Return ONLY valid JSON array of 3-5 items. Each item has title and description fields."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                temperature=0.4,
                max_tokens=300,
                timeout=10
            )

            content = response.choices[0].message.content
            parsed = self._parse_json_list(content)
            return parsed[:5]

        except Exception as e:
            logger.error(f"OpenAI resource recommendations failed: {e}")
            return self._fallback_resources(topic_name)

    def _build_resource_prompt(
        self,
        topic_name: str,
        error_summary: Dict[str, int],
        topic_breakdown: Dict[str, float]
    ) -> str:
        """Build prompt for structured resource recommendations."""
        if error_summary:
            error_text = ", ".join([f"{k} ({v})" for k, v in error_summary.items()])
        else:
            error_text = "None"

        weak_topics = [t for t, acc in topic_breakdown.items() if acc < 0.7]
        weak_text = ", ".join(weak_topics) if weak_topics else "No weak topics detected"

        return (
            "Generate 3-5 short study resources for this exam. "
            "Return ONLY JSON array. Each item: {\"title\": string, \"description\": string}.\n\n"
            f"Topic: {topic_name}\n"
            f"Weak topics: {weak_text}\n"
            f"Error patterns: {error_text}\n"
            "Keep titles concise and descriptions under 15 words."
        )

    def _parse_json_list(self, text: str) -> List[Dict[str, str]]:
        """Parse a JSON array from a model response."""
        cleaned = text.strip()

        # Strip code fences if present
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`")
            lines = cleaned.split("\n")
            cleaned = "\n".join(lines[1:])

        # Find first JSON array
        start = cleaned.find("[")
        end = cleaned.rfind("]")
        if start == -1 or end == -1:
            raise ValueError("No JSON array found")

        payload = cleaned[start:end + 1]
        data = json.loads(payload)

        if not isinstance(data, list):
            raise ValueError("Expected JSON array")

        results = []
        for item in data:
            title = str(item.get("title", "")).strip()
            description = str(item.get("description", "")).strip()
            if title and description:
                results.append({"title": title, "description": description})

        return results

    def _fallback_resources(self, topic_name: str) -> List[Dict[str, str]]:
        """Fallback recommendations if LLM fails."""
        return [
            {"title": f"{topic_name} Refresher", "description": "Review key concepts with short examples."},
            {"title": "Targeted Practice", "description": "Solve 10-15 focused problems on weak areas."},
            {"title": "Common Mistakes", "description": "Study frequent pitfalls and how to avoid them."}
        ]
