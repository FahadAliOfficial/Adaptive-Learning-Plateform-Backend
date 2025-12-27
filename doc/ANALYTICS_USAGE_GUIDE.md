# Multi-Level Analytics - Usage Guide

## Quick Start

The analytics service is now available through REST API endpoints. Here's how to use it:

## 1. Get Student Error Profile

**Endpoint:** `GET /analytics/student/{user_id}/profile`

**Purpose:** Get comprehensive learning analytics for a specific student

**Example Request:**
```bash
curl "http://localhost:8000/analytics/student/user123/profile?language_id=python_3"
```

**Example Response:**
```json
{
  "success": true,
  "user_id": "user123",
  "language_id": "python_3",
  "profile": {
    "major_topic_performance": {
      "UNIV_LOOP": {
        "accuracy_percentage": 52.3,
        "total_questions": 45,
        "most_common_errors": {
          "OFF_BY_ONE_ERROR": 12,
          "INFINITE_LOOP": 4,
          "LOOP_VARIABLE_SCOPE": 2
        }
      },
      "UNIV_VAR": {
        "accuracy_percentage": 78.5,
        "total_questions": 32,
        "most_common_errors": {
          "SCOPE_MISUNDERSTANDING": 3
        }
      }
    },
    "sub_topic_error_patterns": {
      "for_loop_basics": {
        "accuracy_percentage": 45.2,
        "total_questions": 18,
        "error_distribution": {
          "OFF_BY_ONE_ERROR": {
            "count": 8,
            "percentage": 72.7
          },
          "LOOP_BOUNDS_ERROR": {
            "count": 2,
            "percentage": 18.2
          }
        }
      },
      "variable_scope": {
        "accuracy_percentage": 68.0,
        "total_questions": 15,
        "error_distribution": {
          "SCOPE_MISUNDERSTANDING": {
            "count": 3,
            "percentage": 62.5
          }
        }
      }
    },
    "most_common_errors": [
      {
        "error_type": "OFF_BY_ONE_ERROR",
        "occurrences": 12,
        "description": "Loop boundaries or array indexing mistakes"
      },
      {
        "error_type": "SCOPE_MISUNDERSTANDING",
        "occurrences": 5,
        "description": "Variable accessibility confusion"
      }
    ],
    "improvement_areas": [
      "Practice more for_loop_basics (accuracy: 45.2%)",
      "Practice more nested_loops (accuracy: 52.1%)"
    ]
  }
}
```

**Use Case:**
- Student dashboard showing personalized weak areas
- Progress tracking over time
- Targeted practice recommendations

---

## 2. Analyze Sub-Topic Error Distribution

**Endpoint:** `GET /analytics/subtopic/{sub_topic}/errors`

**Purpose:** See what errors students typically make in a specific sub-topic

**Example Request:**
```bash
curl "http://localhost:8000/analytics/subtopic/for_loop_basics/errors?language_id=python_3"
```

**Example Response:**
```json
{
  "success": true,
  "data": {
    "sub_topic": "for_loop_basics",
    "language_id": "python_3",
    "total_attempts": 450,
    "incorrect_attempts": 178,
    "accuracy_rate": 60.4,
    "error_distribution": {
      "OFF_BY_ONE_ERROR": {
        "count": 107,
        "percentage": 60.1
      },
      "LOOP_BOUNDS_ERROR": {
        "count": 45,
        "percentage": 25.3
      },
      "INFINITE_LOOP": {
        "count": 26,
        "percentage": 14.6
      }
    },
    "most_common_error": ["OFF_BY_ONE_ERROR", 107]
  }
}
```

**Use Case:**
- Teacher dashboard showing class-wide difficulties
- Curriculum improvement (focus on problematic areas)
- Content quality validation

---

## 3. Cross-Topic Error Analysis

**Endpoint:** `GET /analytics/student/{user_id}/cross-topic-analysis`

**Purpose:** See where a student makes the same error across different topics

**Example Request:**
```bash
curl "http://localhost:8000/analytics/student/user123/cross-topic-analysis?language_id=python_3"
```

**Example Response:**
```json
{
  "success": true,
  "data": {
    "user_id": "user123",
    "language_id": "python_3",
    "error_patterns_by_subtopic": {
      "OFF_BY_ONE_ERROR": {
        "total_occurrences": 15,
        "subtopic_breakdown": {
          "for_loop_basics": {
            "occurrences": 8,
            "percentage": 53.3
          },
          "array_indexing": {
            "occurrences": 5,
            "percentage": 33.3
          },
          "nested_loops": {
            "occurrences": 2,
            "percentage": 13.3
          }
        }
      },
      "SCOPE_MISUNDERSTANDING": {
        "total_occurrences": 6,
        "subtopic_breakdown": {
          "variable_scope": {
            "occurrences": 3,
            "percentage": 50.0
          },
          "function_parameters": {
            "occurrences": 2,
            "percentage": 33.3
          },
          "nested_loops": {
            "occurrences": 1,
            "percentage": 16.7
          }
        }
      }
    },
    "subtopic_performance": {
      "for_loop_basics": {
        "total_questions": 18,
        "correct_answers": 8,
        "accuracy_percentage": 44.4
      },
      "variable_scope": {
        "total_questions": 12,
        "correct_answers": 8,
        "accuracy_percentage": 66.7
      }
    },
    "recommendations": [
      "Focus on off by one error in for loop basics",
      "Focus on scope misunderstanding in variable scope"
    ]
  }
}
```

**Use Case:**
- Identify systemic conceptual gaps
- Show student if error is isolated or widespread
- Targeted remediation planning

---

## 4. Get Personalized Recommendations

**Endpoint:** `GET /analytics/student/{user_id}/recommendations`

**Purpose:** Get actionable next steps for a student

**Example Request:**
```bash
curl "http://localhost:8000/analytics/student/user123/recommendations?language_id=python_3"
```

**Example Response:**
```json
{
  "success": true,
  "user_id": "user123",
  "language_id": "python_3",
  "improvement_areas": [
    "Practice more for_loop_basics (accuracy: 45.2%)",
    "Practice more nested_loops (accuracy: 52.1%)"
  ],
  "most_common_errors": [
    {
      "error_type": "OFF_BY_ONE_ERROR",
      "occurrences": 12,
      "description": "Loop boundaries or array indexing mistakes"
    },
    {
      "error_type": "SCOPE_MISUNDERSTANDING",
      "occurrences": 5,
      "description": "Variable accessibility confusion"
    }
  ],
  "weak_subtopics": [
    {
      "subtopic": "for_loop_basics",
      "accuracy": 45.2,
      "top_error": "OFF_BY_ONE_ERROR"
    },
    {
      "subtopic": "nested_loops",
      "accuracy": 52.1,
      "top_error": "INFINITE_LOOP"
    }
  ]
}
```

**Use Case:**
- Student dashboard "What should I practice next?"
- Adaptive content selection
- Progress gamification

---

## 5. Class-Wide Insights

**Endpoint:** `GET /analytics/class-insights`

**Purpose:** See which topics are hardest for all students

**Example Request:**
```bash
curl "http://localhost:8000/analytics/class-insights?language_id=python_3"
```

**Example Response:**
```json
{
  "success": true,
  "language_id": "python_3",
  "total_subtopics_analyzed": 24,
  "hardest_subtopics": [
    {
      "subtopic": "nested_loops",
      "accuracy_rate": 42.3,
      "total_attempts": 320,
      "most_common_error": ["INFINITE_LOOP", 45]
    },
    {
      "subtopic": "for_loop_basics",
      "accuracy_rate": 60.4,
      "total_attempts": 450,
      "most_common_error": ["OFF_BY_ONE_ERROR", 107]
    }
  ],
  "easiest_subtopics": [
    {
      "subtopic": "print_statements",
      "accuracy_rate": 94.2,
      "total_attempts": 280,
      "most_common_error": ["SYNTAX_ERROR", 8]
    }
  ]
}
```

**Use Case:**
- Teacher dashboard
- Curriculum design improvements
- Resource allocation (create more content for hard topics)

---

## Integration Examples

### Frontend (React/Vue/Angular)

```javascript
// Get student profile
async function getStudentProfile(userId, languageId) {
  const response = await fetch(
    `/analytics/student/${userId}/profile?language_id=${languageId}`
  );
  const data = await response.json();
  
  // Display weak areas
  console.log("Improvement Areas:", data.profile.improvement_areas);
  console.log("Most Common Errors:", data.profile.most_common_errors);
}

// Get recommendations
async function getRecommendations(userId, languageId) {
  const response = await fetch(
    `/analytics/student/${userId}/recommendations?language_id=${languageId}`
  );
  const data = await response.json();
  
  // Show targeted practice suggestions
  return data.weak_subtopics;
}
```

### Python Client

```python
import requests

# Get student analytics
def get_analytics(user_id, language_id):
    url = f"http://localhost:8000/analytics/student/{user_id}/profile"
    params = {"language_id": language_id}
    
    response = requests.get(url, params=params)
    data = response.json()
    
    # Process analytics
    profile = data["profile"]
    print(f"Weak Sub-Topics: {profile['improvement_areas']}")
    print(f"Common Errors: {profile['most_common_errors']}")
    
    return profile

# Usage
analytics = get_analytics("user123", "python_3")
```

---

## Backend Integration (From Other Services)

```python
from sqlalchemy.orm import Session
from services.multi_level_analytics_service import MultiLevelAnalyticsService

def generate_adaptive_content(user_id: str, language_id: str, db: Session):
    """
    Use analytics to select appropriate questions for student.
    """
    # Get student's weak areas
    analytics = MultiLevelAnalyticsService(db)
    profile = analytics.get_student_error_profile(user_id, language_id)
    
    # Extract weak sub-topics
    weak_subtopics = [
        subtopic for subtopic, data in profile["sub_topic_error_patterns"].items()
        if data["accuracy_percentage"] < 60
    ]
    
    # Generate more questions from weak areas
    # ... (integrate with question selection service)
    
    return weak_subtopics
```

---

## Tips for Maximum Value

1. **Call after every session**: Update analytics after each practice session
2. **Display visually**: Show charts/graphs of error patterns
3. **Gamify improvement**: Track reduction in specific error types over time
4. **Adaptive selection**: Use analytics to pick next questions automatically
5. **Teacher insights**: Provide class-wide analytics for instructors

---

## Performance Considerations

- Analytics queries aggregate historical data - may be slow for users with 100+ sessions
- Consider caching frequently accessed profiles
- Use background jobs for class-wide analytics (many students)
- Index `user_id`, `language_id`, and `sub_topic` columns for faster queries
