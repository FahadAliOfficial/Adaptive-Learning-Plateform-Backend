# Complete System Workflow - FYP Backend Architecture

## Table of Contents
1. [System Overview](#system-overview)
2. [Scenario A: State Vector Generation (RL Decision)](#scenario-a-state-vector-generation)
3. [Scenario B: Exam Submission (Learning)](#scenario-b-exam-submission)
4. [Scenario C: User Registration (Onboarding)](#scenario-c-user-registration)
5. [Data Flow Architecture](#data-flow-architecture)
6. [File Dependencies Map](#file-dependencies-map)
7. [Database Schema Overview](#database-schema-overview)

---

# System Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                         FYP BACKEND SYSTEM                          │
│                  Adaptive RL-Based Learning Platform                │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌──────────────┐      ┌──────────────┐      ┌──────────────┐     │
│  │  SCENARIO A  │      │  SCENARIO B  │      │  SCENARIO C  │     │
│  │  Get State   │      │   Submit     │      │   Register   │     │
│  │  Vector      │      │   Exam       │      │   User       │     │
│  └──────────────┘      └──────────────┘      └──────────────┘     │
│         │                      │                      │            │
│         ├──────────────────────┼──────────────────────┤            │
│         ▼                      ▼                      ▼            │
│  ┌─────────────────────────────────────────────────────────────┐  │
│  │              CONFIGURATION LAYER (Singleton)                 │  │
│  │  • config.py    - Loads JSON, builds indices                │  │
│  │  • schemas.py   - Validates requests/responses               │  │
│  └─────────────────────────────────────────────────────────────┘  │
│         │                      │                      │            │
│         ▼                      ▼                      ▼            │
│  ┌─────────────────────────────────────────────────────────────┐  │
│  │                   DATA SOURCES                               │  │
│  │  ┌────────────────┐  ┌────────────────┐  ┌──────────────┐  │  │
│  │  │final_curriculum│  │transition_map  │  │  PostgreSQL  │  │  │
│  │  │   .json        │  │    .json       │  │   Database   │  │  │
│  │  └────────────────┘  └────────────────┘  └──────────────┘  │  │
│  └─────────────────────────────────────────────────────────────┘  │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

# Scenario A: State Vector Generation (RL Decision)

**Purpose:** Generate current learning state for RL model to decide next topic

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    SCENARIO A: GET STATE VECTOR                         │
└─────────────────────────────────────────────────────────────────────────┘

[1] FRONTEND REQUEST
    │
    ├── POST /api/state-vector
    │   Body: {
    │     "user_id": "550e8400-...",
    │     "language_id": "python_3"
    │   }
    │
    ▼

[2] PYDANTIC VALIDATION (schemas.py)
    │
    ├── StateVectorRequest validates:
    │   ✓ user_id is valid UUID
    │   ✓ language_id in ["python_3", "javascript_es6", ...]
    │
    ▼

[3] STATE VECTOR SERVICE (state_vector_service.py)
    │
    ├── generate_vector(request)
    │   │
    │   ├─▶ [3.1] Load Config Singleton
    │   │   │
    │   │   └─▶ config.py → get_config()
    │   │       │
    │   │       ├─▶ Loads: final_curriculum.json
    │   │       ├─▶ Loads: transition_map.json
    │   │       └─▶ Builds: mapping_to_topics, universal_mappings, valid_languages
    │   │
    │   ├─▶ [3.2] Initialize Vector (dynamic dimensions)
    │   │   │
    │   │   └─▶ vector_size = num_languages + (num_mappings × 3) + 8
    │   │       Example: 5 languages + (8 mappings × 3) + 8 = 37 dimensions
    │   │
    │   ├─▶ [3.3] Populate Language One-Hot
    │   │   │
    │   │   └─▶ [0,0,1,0,0] if python_3 is 3rd in languages_order
    │   │
    │   ├─▶ [3.4] Fetch Decayed Mastery Scores
    │   │   │
    │   │   └─▶ Query PostgreSQL:
    │   │       SELECT mapping_id, mastery_score, last_practiced_at
    │   │       FROM student_state
    │   │       WHERE user_id=:u AND language_id=:l
    │   │       │
    │   │       ├─▶ For each topic:
    │   │       │   days_passed = (now - last_practiced_at).days
    │   │       │   decay_factor = e^(-0.02 × days_passed)
    │   │       │   decayed_mastery = original × decay_factor
    │   │       │
    │   │       └─▶ Fills indices [5-12] with decayed scores
    │   │
    │   ├─▶ [3.5] Fetch Fluency Scores
    │   │   │
    │   │   └─▶ Query PostgreSQL: SELECT fluency_score FROM student_state
    │   │       └─▶ Fills indices [13-20]
    │   │
    │   ├─▶ [3.6] Fetch Confidence Scores
    │   │   │
    │   │   └─▶ Query PostgreSQL: SELECT confidence_score FROM student_state
    │   │       └─▶ Fills indices [21-28]
    │   │
    │   ├─▶ [3.7] Calculate Behavioral Metrics (8 dimensions)
    │   │   │
    │   │   ├─▶ Query last session:
    │   │   │   SELECT overall_score, difficulty_assigned, created_at
    │   │   │   FROM exam_sessions
    │   │   │   ORDER BY created_at DESC LIMIT 1
    │   │   │
    │   │   ├─▶ Query user total exams:
    │   │   │   SELECT total_exams_taken FROM users WHERE id=:u
    │   │   │
    │   │   ├─▶ Calculate gate_readiness:
    │   │   │   - For each soft_gate, check prerequisite mastery
    │   │   │   - Apply weighted average
    │   │   │   - Return 0-1 readiness score
    │   │   │
    │   │   └─▶ Fills indices [29-36]:
    │   │       [29] last_accuracy
    │   │       [30] last_difficulty
    │   │       [31] avg_fluency
    │   │       [32] stability (inverse of score variance)
    │   │       [33] days_inactive
    │   │       [34] gate_readiness
    │   │       [35] session_confidence (cold-start signal)
    │   │       [36] performance_velocity (fast learner flag)
    │   │
    │   └─▶ [3.8] Generate Rich Metadata
    │       │
    │       ├─▶ Find strongest/weakest topics
    │       ├─▶ Identify topics needing review
    │       ├─▶ Check prerequisites status
    │       ├─▶ Calculate cross-language transfer potential
    │       └─▶ Get recent error patterns
    │
    ▼

[4] RESPONSE CONSTRUCTION (schemas.py)
    │
    ├── StateVectorResponse validates:
    │   ✓ state_vector has correct dimensions
    │   ✓ metadata is valid dict
    │
    ▼

[5] FRONTEND RECEIVES
    │
    └── Response: {
          "state_vector": [0,0,1,0,0, 0.68,0.15,0.92,...],
          "metadata": {
            "strongest_topic": {"id": "UNIV_FUNC", "mastery": 0.92},
            "weakest_topic": {"id": "UNIV_COND", "mastery": 0.15},
            "needs_review": ["UNIV_VAR"],
            "gate_readiness": 0.85,
            "session_confidence": 0.75,
            "prerequisites_status": {...},
            "transfer_potential": [...]
          }
        }

[6] RL MODEL CONSUMES
    │
    └── Uses state_vector to decide:
        "Which topic should student practice next?"
        → Outputs: major_topic_id (e.g., "PY_LOOP_01")
```

---

# Scenario B: Exam Submission (Learning)

**Purpose:** Process exam results and update student mastery state

```
┌─────────────────────────────────────────────────────────────────────────┐
│                  SCENARIO B: EXAM SUBMISSION PROCESSING                 │
└─────────────────────────────────────────────────────────────────────────┘

[1] FRONTEND REQUEST
    │
    ├── POST /api/submit-exam
    │   Body: {
    │     "user_id": "550e8400-...",
    │     "language_id": "python_3",
    │     "major_topic_id": "PY_VAR_01",
    │     "session_type": "practice",
    │     "results": [
    │       {
    │         "q_id": "uuid-1",
    │         "sub_topic": "variable_declaration",
    │         "difficulty": 0.3,
    │         "is_correct": true,
    │         "time_spent": 45.2,
    │         "expected_time": 60.0,
    │         "error_type": null
    │       },
    │       ... (5-50 questions)
    │     ],
    │     "total_time_seconds": 420
    │   }
    │
    ▼

[2] PYDANTIC VALIDATION (schemas.py)
    │
    ├── ExamSubmissionPayload validates:
    │   ✓ user_id is valid UUID
    │   ✓ language_id in valid literals
    │   ✓ major_topic_id matches format (XX_YYYY_01)
    │   ✓ results has 5-50 questions
    │   ✓ Each QuestionResult has valid difficulty (0-1)
    │
    ▼

[3] GRADING SERVICE (grading_service.py)
    │
    ├── process_submission(payload)
    │   │
    │   ├─▶ [3.1] Load Config Singleton
    │   │   │
    │   │   └─▶ config.py → get_config()
    │   │       └─▶ Accesses transition_map.json for rules
    │   │
    │   ├─▶ [3.2] Calculate Session Statistics
    │   │   │
    │   │   ├─▶ accuracy = corrects / total
    │   │   │   Example: 8/10 = 0.80
    │   │   │
    │   │   ├─▶ avg_difficulty = Σ(q.difficulty) / count
    │   │   │   Example: (0.3+0.3+0.6+...)/10 = 0.45
    │   │   │
    │   │   └─▶ fluency_ratio = expected_time / actual_time
    │   │       Example: 600/420 = 1.43 (43% faster!)
    │   │
    │   ├─▶ [3.3] Convert to Universal Mapping
    │   │   │
    │   │   └─▶ config.get_mapping_id('python_3', 'PY_VAR_01')
    │   │       └─▶ Returns: 'UNIV_VAR'
    │   │
    │   ├─▶ [3.4] Check Soft Gates (Prerequisites)
    │   │   │
    │   │   ├─▶ config.get_soft_gate('UNIV_VAR')
    │   │   │   └─▶ Returns: {
    │   │   │         "prerequisite_mappings": ["UNIV_SYN_LOGIC"],
    │   │   │         "minimum_allowable_score": 0.60
    │   │   │       }
    │   │   │
    │   │   └─▶ Query PostgreSQL:
    │   │       SELECT mapping_id, mastery_score
    │   │       FROM student_state
    │   │       WHERE user_id=:u AND language_id=:l
    │   │         AND mapping_id IN ('UNIV_SYN_LOGIC')
    │   │       │
    │   │       └─▶ Check if each prereq >= 0.60
    │   │           If not: violations = ["UNIV_SYN_LOGIC (has 0.45, needs 0.60)"]
    │   │
    │   ├─▶ [3.5] Update Mastery (EMA Algorithm)
    │   │   │
    │   │   ├─▶ Query current state:
    │   │   │   SELECT mastery_score, fluency_score, confidence_score
    │   │   │   FROM student_state
    │   │   │   WHERE user_id=:u AND mapping_id=:m AND language_id=:l
    │   │   │   │
    │   │   │   └─▶ old_mastery = 0.65 (example)
    │   │   │
    │   │   ├─▶ Calculate performance:
    │   │   │   performance = accuracy × difficulty
    │   │   │   = 0.80 × 0.45 = 0.36
    │   │   │
    │   │   ├─▶ Apply soft gate penalty (if violations exist):
    │   │   │   penalty_factor = e^(-penalty_steepness)
    │   │   │   = e^(-2.5) = 0.082
    │   │   │   performance *= 0.082 = 0.0295
    │   │   │
    │   │   ├─▶ Detect high-velocity learners:
    │   │   │   if accuracy > 0.9 AND fluency > 1.2 AND difficulty > 0.6:
    │   │   │     retention = 0.5, innovation = 0.5
    │   │   │   else:
    │   │   │     retention = 0.7, innovation = 0.3
    │   │   │
    │   │   ├─▶ Apply EMA formula:
    │   │   │   new_mastery = (old_mastery × retention) + (performance × innovation)
    │   │   │   = (0.65 × 0.7) + (0.36 × 0.3)
    │   │   │   = 0.455 + 0.108 = 0.563
    │   │   │
    │   │   ├─▶ Calculate error remediation bonus:
    │   │   │   - Query previous session errors
    │   │   │   - Check if current session fixed them
    │   │   │   - Add bonus (max +0.15)
    │   │   │   new_mastery += 0.08 (if fixed errors)
    │   │   │   = 0.643
    │   │   │
    │   │   ├─▶ Update fluency:
    │   │   │   new_fluency = (old_fluency × 0.8) + (fluency × 0.2)
    │   │   │   = (1.2 × 0.8) + (1.43 × 0.2) = 1.246
    │   │   │
    │   │   ├─▶ Update confidence:
    │   │   │   score_delta = |new_mastery - old_mastery|
    │   │   │   confidence_boost = 1.0 - score_delta
    │   │   │   new_confidence = (old_confidence × 0.9) + (confidence_boost × 0.1)
    │   │   │
    │   │   └─▶ Upsert to database:
    │   │       INSERT INTO student_state (...)
    │   │       VALUES (user_id, mapping_id, language_id, 0.643, 1.246, ...)
    │   │       ON CONFLICT (user_id, mapping_id, language_id)
    │   │       DO UPDATE SET mastery_score = EXCLUDED.mastery_score, ...
    │   │
    │   ├─▶ [3.6] Apply Synergy Bonuses (if accuracy >= 70%)
    │   │   │
    │   │   ├─▶ config.get_synergy_bonuses('UNIV_VAR')
    │   │   │   └─▶ Returns: [] (no synergies for UNIV_VAR)
    │   │   │
    │   │   └─▶ For each synergy:
    │   │       UPDATE student_state
    │   │       SET mastery_score = LEAST(mastery_score + :bonus, 1.0)
    │   │       WHERE user_id=:u AND mapping_id=:target AND language_id=:l
    │   │       │
    │   │       └─▶ synergies_applied = ["UNIV_COLL (+0.12)"]
    │   │
    │   ├─▶ [3.7] Apply Cross-Language Transfer
    │   │   │
    │   │   ├─▶ Query other languages:
    │   │   │   SELECT DISTINCT language_id
    │   │   │   FROM student_state
    │   │   │   WHERE user_id=:u AND language_id != 'python_3'
    │   │   │   └─▶ Returns: ['java_17']
    │   │   │
    │   │   ├─▶ Get mastery in source language:
    │   │   │   SELECT mastery_score
    │   │   │   FROM student_state
    │   │   │   WHERE user_id=:u AND language_id='java_17' AND mapping_id='UNIV_VAR'
    │   │   │   └─▶ Returns: 0.80
    │   │   │
    │   │   ├─▶ Find transfer coefficient:
    │   │   │   From transition_map.json → cross_language_transfer:
    │   │   │   {source: 'java_17', target: 'python_3', logic_acceleration: 0.85}
    │   │   │
    │   │   ├─▶ Calculate boost:
    │   │   │   boost = source_mastery × logic_accel × 0.1
    │   │   │   = 0.80 × 0.85 × 0.1 = 0.068
    │   │   │
    │   │   └─▶ Apply boost:
    │   │       UPDATE student_state
    │   │       SET mastery_score = LEAST(mastery_score + 0.068, 1.0)
    │   │       WHERE user_id=:u AND language_id='python_3' AND mapping_id='UNIV_VAR'
    │   │       │
    │   │       └─▶ transfer_bonuses = ["UNIV_VAR from java_17 (+0.07)"]
    │   │
    │   ├─▶ [3.8] Apply Concept Interdependencies
    │   │   │
    │   │   └─▶ From concept_interdependencies.json:
    │   │       {mapping_a: 'UNIV_VAR', mapping_b: 'UNIV_FUNC', coefficient: 0.10}
    │   │       │
    │   │       ├─▶ If practiced UNIV_VAR, boost UNIV_FUNC
    │   │       │   boost = new_mastery × coefficient
    │   │       │   = 0.643 × 0.10 = 0.064
    │   │       │
    │   │       └─▶ UPDATE student_state
    │   │           SET mastery_score = LEAST(mastery_score + 0.064, 1.0)
    │   │           WHERE mapping_id='UNIV_FUNC' AND language_id='python_3'
    │   │           │
    │   │           └─▶ interdependency_boosts = ["UNIV_FUNC:+0.064"]
    │   │
    │   ├─▶ [3.9] Increment Total Exams Counter (Cold-Start Signal)
    │   │   │
    │   │   └─▶ UPDATE users
    │   │       SET total_exams_taken = total_exams_taken + 1
    │   │       WHERE id = :user_id
    │   │
    │   ├─▶ [3.10] Save Session History
    │   │   │
    │   │   ├─▶ INSERT INTO exam_sessions:
    │   │   │   - session_id (UUID)
    │   │   │   - user_id, language_id, major_topic_id
    │   │   │   - overall_score (accuracy)
    │   │   │   - difficulty_assigned
    │   │   │   - time_taken_seconds
    │   │   │
    │   │   └─▶ INSERT INTO exam_details:
    │   │       - session_id
    │   │       - questions_snapshot (JSONB)
    │   │         Contains: [{q_id, sub_topic, difficulty, is_correct, error_type}, ...]
    │   │
    │   ├─▶ [3.11] Generate Recommendations
    │   │   │
    │   │   ├─▶ If has violations:
    │   │   │   "⚠️ Strengthen prerequisites: UNIV_SYN_LOGIC"
    │   │   │
    │   │   ├─▶ Suggest difficulty tier:
    │   │   │   tier = config.get_difficulty_tier('UNIV_VAR', 0.643)
    │   │   │   "🟡 Recommended tier: INTERMEDIATE"
    │   │   │
    │   │   ├─▶ Check mastery level:
    │   │   │   if mastery >= 0.75: "✅ Ready to advance"
    │   │   │   elif mastery >= 0.65: "📈 Good progress"
    │   │   │   else: "📚 Keep practicing"
    │   │   │
    │   │   ├─▶ Find topics needing review:
    │   │   │   SELECT mapping_id FROM student_state
    │   │   │   WHERE mastery_score < 0.65
    │   │   │   "🔄 Review needed for: UNIV_COND"
    │   │   │
    │   │   └─▶ Cross-language transfer opportunities:
    │   │       "🌐 Try java_17 - 68% knowledge transfer"
    │   │
    │   └─▶ [3.12] Commit Transaction
    │       │
    │       └─▶ self.db.commit()
    │           All updates atomic!
    │
    ▼

[4] RESPONSE CONSTRUCTION (schemas.py)
    │
    ├── MasteryUpdateResponse validates:
    │   ✓ All fields present
    │   ✓ Scores are 0-1 floats
    │
    ▼

[5] FRONTEND RECEIVES
    │
    └── Response: {
          "success": true,
          "session_id": "abc-123-...",
          "accuracy": 0.800,
          "fluency_ratio": 1.43,
          "new_mastery_score": 0.643,
          "synergies_applied": [
            "UNIV_FUNC:+0.064"
          ],
          "soft_gate_violations": [],
          "recommendations": [
            "🟡 Recommended tier: INTERMEDIATE",
            "📈 Good progress (0.643). Practice more to solidify.",
            "🔄 Review needed for: UNIV_COND",
            "🌐 Try java_17 - 68% knowledge transfer"
          ]
        }

[6] FRONTEND UPDATES UI
    │
    ├─▶ Shows new mastery score with animation
    ├─▶ Displays synergy badges
    ├─▶ Shows recommendation cards
    └─▶ Updates progress bars
```

---

# Scenario C: User Registration (Onboarding)

**Purpose:** Create new user account and prime initial knowledge state

```
┌─────────────────────────────────────────────────────────────────────────┐
│                   SCENARIO C: USER REGISTRATION                         │
└─────────────────────────────────────────────────────────────────────────┘

[1] FRONTEND REQUEST
    │
    ├── POST /api/register
    │   Body: {
    │     "email": "john@example.com",
    │     "password": "secure123",
    │     "language_id": "python_3",
    │     "experience_level": "intermediate"
    │   }
    │
    ▼

[2] PYDANTIC VALIDATION (schemas.py)
    │
    ├── UserRegistrationPayload validates:
    │   ✓ email contains '@' and '.'
    │   ✓ password length >= 6
    │   ✓ language_id in valid literals
    │   ✓ experience_level in ["beginner", "intermediate", "advanced"]
    │   │
    │   └─▶ Email normalized to lowercase: "john@example.com"
    │
    ▼

[3] USER SERVICE (user_service.py)
    │
    ├── register_user(payload)
    │   │
    │   ├─▶ [3.1] Check Email Uniqueness
    │   │   │
    │   │   └─▶ Query PostgreSQL:
    │   │       SELECT id FROM users WHERE email = 'john@example.com'
    │   │       │
    │   │       └─▶ If exists: raise ValueError("Email already registered")
    │   │
    │   ├─▶ [3.2] Create User Record
    │   │   │
    │   │   ├─▶ Generate UUID: user_id = "550e8400-e29b-..."
    │   │   │
    │   │   └─▶ INSERT INTO users:
    │   │       INSERT INTO users (id, email, password_hash, last_active_language)
    │   │       VALUES ('550e8400-...', 'john@example.com', 'secure123', 'python_3')
    │   │       Note: In production, hash password with bcrypt!
    │   │
    │   ├─▶ [3.3] Load Experience Configuration
    │   │   │
    │   │   └─▶ config.get_experience_config('intermediate')
    │   │       │
    │   │       └─▶ From transition_map.json → experience_levels:
    │   │           {
    │   │             "label": "Intermediate",
    │   │             "assumed_mastered": [
    │   │               "UNIV_SYN_LOGIC",
    │   │               "UNIV_SYN_PREC",
    │   │               "UNIV_VAR",
    │   │               "UNIV_COND"
    │   │             ],
    │   │             "initial_mastery_estimate": 0.75,
    │   │             "starting_mapping_id": "UNIV_LOOP"
    │   │           }
    │   │
    │   ├─▶ [3.4] Pre-Populate Assumed Knowledge
    │   │   │
    │   │   └─▶ For each mapping in assumed_mastered:
    │   │       │
    │   │       ├─▶ INSERT INTO student_state:
    │   │       │   (user_id, mapping_id, language_id, mastery_score, fluency_score, confidence_score)
    │   │       │   VALUES
    │   │       │   ('550e8400-...', 'UNIV_SYN_LOGIC', 'python_3', 0.75, 1.2, 0.5),
    │   │       │   ('550e8400-...', 'UNIV_SYN_PREC', 'python_3', 0.75, 1.2, 0.5),
    │   │       │   ('550e8400-...', 'UNIV_VAR', 'python_3', 0.75, 1.2, 0.5),
    │   │       │   ('550e8400-...', 'UNIV_COND', 'python_3', 0.75, 1.2, 0.5)
    │   │       │
    │   │       └─▶ Primes student with 4 topics at 75% mastery
    │   │           (Skips beginner topics, starts at intermediate level)
    │   │
    │   ├─▶ [3.5] Get Starting Topic
    │   │   │
    │   │   └─▶ config.get_major_topic_id('python_3', 'UNIV_LOOP')
    │   │       │
    │   │       └─▶ Returns: "PY_LOOP_01"
    │   │           (Language-specific topic ID for Python loops)
    │   │
    │   └─▶ [3.6] Commit Transaction
    │       │
    │       └─▶ self.db.commit()
    │
    ▼

[4] RESPONSE CONSTRUCTION (schemas.py)
    │
    ├── UserRegistrationResponse validates:
    │   ✓ user_id is valid UUID
    │   ✓ starting_topic is non-empty string
    │
    ▼

[5] FRONTEND RECEIVES
    │
    └── Response: {
          "user_id": "550e8400-e29b-41d4-a716-446655440000",
          "message": "User registered successfully at intermediate level.",
          "starting_topic": "PY_LOOP_01",
          "experience_level": "intermediate"
        }

[6] FRONTEND ACTIONS
    │
    ├─▶ Store user_id in session/localStorage
    ├─▶ Navigate to dashboard
    └─▶ Show welcome message: "Start with: Python Loops (PY_LOOP_01)"
```

---

# Data Flow Architecture

```
┌───────────────────────────────────────────────────────────────────────────┐
│                        COMPLETE DATA FLOW MAP                             │
└───────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────┐
│                        STATIC CONFIGURATION                             │
│  ┌────────────────────────────────────────────────────────────────┐    │
│  │  core/final_curriculum.json (353 lines)                        │    │
│  │  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  │    │
│  │  Purpose: Master curriculum definition                         │    │
│  │  Structure:                                                     │    │
│  │    - 5 languages (python_3, javascript_es6, java_17, ...)     │    │
│  │    - 8 universal topics per language (40 topics total)         │    │
│  │  Content:                                                       │    │
│  │    - major_topic_id (e.g., PY_VAR_01, JS_FUNC_01)             │    │
│  │    - mapping_id (e.g., UNIV_VAR, UNIV_FUNC)                   │    │
│  │    - name, global_difficulty, prerequisites                    │    │
│  │    - sub_topics array                                          │    │
│  └────────────────────────────────────────────────────────────────┘    │
│                                                                          │
│  ┌────────────────────────────────────────────────────────────────┐    │
│  │  core/transition_map.json (1443 lines)                         │    │
│  │  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  │    │
│  │  Purpose: Learning rules and knowledge transfer policies       │    │
│  │  16 Sections:                                                   │    │
│  │    ✓ config (decay_rate, thresholds)                          │    │
│  │    ✓ experience_levels (beginner/intermediate/advanced)       │    │
│  │    ✓ universal_transitions (Phase 2)                          │    │
│  │    ✓ intra_language_synergy (same-language bonuses)           │    │
│  │    ✓ cross_language_transfer (multi-language learning)        │    │
│  │    ✓ mapping_specific_cross_language_transfer                 │    │
│  │    ✓ soft_gates (prerequisite enforcement)                    │    │
│  │    ✓ language_specific_modifiers (Phase 2)                    │    │
│  │    ✓ question_difficulty_tiers (beginner/int/adv)             │    │
│  │    ✓ adaptive_difficulty_curves (Phase 2)                     │    │
│  │    ✓ temporal_learning_patterns (Phase 2)                     │    │
│  │    ✓ spaced_repetition_intervals (Phase 2)                    │    │
│  │    ✓ milestone_projects (Phase 2)                             │    │
│  │    ✓ error_pattern_taxonomy (remediation bonuses)             │    │
│  │    ✓ prerequisite_strength_weights (Phase 2)                  │    │
│  │    ✓ concept_interdependencies                                │    │
│  └────────────────────────────────────────────────────────────────┘    │
│                                                                          │
│  ┌────────────────────────────────────────────────────────────────┐    │
│  │  core/concept_interdependencies_config.json                    │    │
│  │  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  │    │
│  │  Purpose: Bidirectional concept reinforcement                  │    │
│  │  Content: mapping_a ↔ mapping_b relationships                 │    │
│  └────────────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                        CONFIGURATION LAYER                              │
│  ┌────────────────────────────────────────────────────────────────┐    │
│  │  services/config.py (143 lines)                                │    │
│  │  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  │    │
│  │  Class: CurriculumConfig                                       │    │
│  │  Pattern: Singleton with @lru_cache                            │    │
│  │  Responsibilities:                                              │    │
│  │    1. Load both JSON files on initialization                   │    │
│  │    2. Build fast lookup indices:                               │    │
│  │       - valid_languages: Set of 5 languages                    │    │
│  │       - mapping_to_topics: {mapping_id: {lang_id: topic_info}} │    │
│  │       - universal_mappings: Ordered list of 8 mappings         │    │
│  │    3. Provide helper methods:                                  │    │
│  │       - get_mapping_id(lang, topic) → mapping                  │    │
│  │       - get_major_topic_id(lang, mapping) → topic              │    │
│  │       - get_synergy_bonuses(mapping) → bonuses                 │    │
│  │       - get_soft_gate(mapping) → gate rules                    │    │
│  │       - get_difficulty_tier(mapping, mastery) → tier           │    │
│  │       - get_decay_rate() → 0.02                                │    │
│  │       - get_review_multiplier() → 1.5                          │    │
│  │       - get_maintenance_threshold() → 0.65                     │    │
│  │       - get_experience_config(level) → priming config          │    │
│  └────────────────────────────────────────────────────────────────┘    │
│                                                                          │
│  ┌────────────────────────────────────────────────────────────────┐    │
│  │  services/schemas.py (115 lines)                               │    │
│  │  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  │    │
│  │  Framework: Pydantic (automatic validation)                    │    │
│  │  Models:                                                        │    │
│  │    Request Models:                                             │    │
│  │      - QuestionResult (individual question data)               │    │
│  │      - ExamSubmissionPayload (complete exam)                   │    │
│  │      - StateVectorRequest (RL state request)                   │    │
│  │      - UserRegistrationPayload (new user)                      │    │
│  │    Response Models:                                            │    │
│  │      - MasteryUpdateResponse (exam results)                    │    │
│  │      - StateVectorResponse (RL state + metadata)               │    │
│  │      - UserRegistrationResponse (user creation)                │    │
│  │  Custom Validators:                                            │    │
│  │    - UUID format validation                                    │    │
│  │    - Email format validation                                   │    │
│  │    - Topic ID format validation (XX_YYYY_01)                   │    │
│  │    - Difficulty range validation (0.0-1.0)                     │    │
│  └────────────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                        SERVICE LAYER                                    │
│                                                                          │
│  ┌────────────────────────────────────────────────────────────────┐    │
│  │  services/grading_service.py (671 lines)                       │    │
│  │  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  │    │
│  │  Class: GradingService                                         │    │
│  │  Purpose: Process exams, update mastery (SCENARIO B)           │    │
│  │  Key Methods:                                                   │    │
│  │    - process_submission() [MAIN ENTRY]                         │    │
│  │      → Calculate statistics                                    │    │
│  │      → Check soft gates                                        │    │
│  │      → Update mastery (EMA)                                    │    │
│  │      → Apply synergies                                         │    │
│  │      → Apply cross-language transfer                           │    │
│  │      → Apply interdependencies                                 │    │
│  │      → Save session history                                    │    │
│  │      → Generate recommendations                                │    │
│  │    - _update_mastery()                                         │    │
│  │      Formula: (old × 0.7) + (performance × 0.3) + remediation  │    │
│  │      Handles: EMA, soft gate penalties, high-velocity learners │    │
│  │    - _apply_synergy()                                          │    │
│  │      Boosts related topics (same language only)                │    │
│  │    - _apply_cross_language_transfer()                          │    │
│  │      Boosts from other languages                               │    │
│  │    - _apply_concept_interdependencies()                        │    │
│  │      Bidirectional reinforcement                               │    │
│  │    - _calculate_error_remediation_bonus()                      │    │
│  │      Rewards fixing previous mistakes                          │    │
│  │    - _check_soft_gates()                                       │    │
│  │      Validates prerequisites                                   │    │
│  │    - _generate_recommendations()                               │    │
│  │      Suggests next steps                                       │    │
│  └────────────────────────────────────────────────────────────────┘    │
│                                                                          │
│  ┌────────────────────────────────────────────────────────────────┐    │
│  │  services/state_vector_service.py (487 lines)                  │    │
│  │  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  │    │
│  │  Class: StateVectorGenerator                                   │    │
│  │  Purpose: Generate RL state vectors (SCENARIO A)               │    │
│  │  Dynamic Dimensions: 5 + (8×3) + 8 = 37 (adapts to curriculum) │    │
│  │  Vector Structure:                                              │    │
│  │    [0-4]   Language one-hot encoding                           │    │
│  │    [5-12]  Decayed mastery scores (8 mappings)                 │    │
│  │    [13-20] Fluency scores (8 mappings)                         │    │
│  │    [21-28] Confidence scores (8 mappings)                      │    │
│  │    [29-36] Behavioral metrics:                                 │    │
│  │      [29] last_accuracy                                        │    │
│  │      [30] last_difficulty                                      │    │
│  │      [31] avg_fluency                                          │    │
│  │      [32] stability (inverse variance)                         │    │
│  │      [33] days_inactive                                        │    │
│  │      [34] gate_readiness                                       │    │
│  │      [35] session_confidence (cold-start)                      │    │
│  │      [36] performance_velocity (fast learner)                  │    │
│  │  Key Methods:                                                   │    │
│  │    - generate_vector() [MAIN ENTRY]                            │    │
│  │    - _get_decayed_mastery()                                    │    │
│  │      Formula: original × e^(-0.02 × days)                      │    │
│  │    - _get_behavioral_metrics()                                 │    │
│  │      Queries sessions, calculates stability, gate readiness    │    │
│  │    - _generate_metadata()                                      │    │
│  │      Creates human-readable state explanation                  │    │
│  │    - _get_prerequisites_status()                               │    │
│  │      Checks which topics have prereqs met                      │    │
│  │    - _get_transfer_potential()                                 │    │
│  │      Calculates best cross-language opportunities              │    │
│  │    - _get_recent_errors()                                      │    │
│  │      Extracts error patterns from last 5 sessions              │    │
│  └────────────────────────────────────────────────────────────────┘    │
│                                                                          │
│  ┌────────────────────────────────────────────────────────────────┐    │
│  │  services/user_service.py (147 lines)                          │    │
│  │  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  │    │
│  │  Class: UserService                                            │    │
│  │  Purpose: User registration and state priming (SCENARIO C)     │    │
│  │  Key Methods:                                                   │    │
│  │    - register_user() [MAIN ENTRY]                              │    │
│  │      → Check email uniqueness                                  │    │
│  │      → Create user record                                      │    │
│  │      → Load experience config                                  │    │
│  │      → Pre-populate assumed knowledge                          │    │
│  │      → Return starting topic                                   │    │
│  │    - get_user_starting_topic()                                 │    │
│  │      Recommends topic when switching languages                 │    │
│  └────────────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                        DATABASE LAYER                                   │
│  ┌────────────────────────────────────────────────────────────────┐    │
│  │  PostgreSQL Database                                           │    │
│  │  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  │    │
│  │  Table: users                                                   │    │
│  │    - id (UUID, PK)                                             │    │
│  │    - email (unique)                                            │    │
│  │    - password_hash                                             │    │
│  │    - last_active_language                                      │    │
│  │    - total_exams_taken (counter for cold-start)                │    │
│  │    - created_at                                                │    │
│  │                                                                 │    │
│  │  Table: student_state                                          │    │
│  │    - user_id (FK → users.id)                                   │    │
│  │    - mapping_id (e.g., UNIV_VAR)                               │    │
│  │    - language_id (e.g., python_3)                              │    │
│  │    - mastery_score (0.0-1.0)                                   │    │
│  │    - fluency_score (0.0-2.0)                                   │    │
│  │    - confidence_score (0.0-1.0)                                │    │
│  │    - last_practiced_at (timestamp)                             │    │
│  │    - last_updated (timestamp)                                  │    │
│  │    UNIQUE (user_id, mapping_id, language_id)                   │    │
│  │                                                                 │    │
│  │  Table: exam_sessions                                          │    │
│  │    - id (UUID, PK)                                             │    │
│  │    - user_id (FK → users.id)                                   │    │
│  │    - language_id                                               │    │
│  │    - major_topic_id                                            │    │
│  │    - session_type (diagnostic/practice)                        │    │
│  │    - overall_score (accuracy)                                  │    │
│  │    - difficulty_assigned                                       │    │
│  │    - time_taken_seconds                                        │    │
│  │    - rl_action_taken                                           │    │
│  │    - created_at                                                │    │
│  │                                                                 │    │
│  │  Table: exam_details                                           │    │
│  │    - session_id (FK → exam_sessions.id)                        │    │
│  │    - questions_snapshot (JSONB)                                │    │
│  │      Contains: [{q_id, sub_topic, difficulty, is_correct,     │    │
│  │                  time_spent, error_type}, ...]                 │    │
│  │    - recommendations (JSONB)                                   │    │
│  │    - synergy_applied (boolean)                                 │    │
│  └────────────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────────────┘
```

---

# File Dependencies Map

```
┌─────────────────────────────────────────────────────────────────────────┐
│                       FILE DEPENDENCY GRAPH                             │
└─────────────────────────────────────────────────────────────────────────┘

main.py (FastAPI app)
│
├─▶ services/grading_service.py
│   │
│   ├─▶ services/config.py ────────┐
│   │   │                          │
│   │   ├─▶ core/final_curriculum.json
│   │   └─▶ core/transition_map.json
│   │                                │
│   └─▶ services/schemas.py          │
│       │                            │
│       └─▶ (Pydantic BaseModel)     │
│                                    │
├─▶ services/state_vector_service.py │
│   │                                │
│   ├─▶ services/config.py ──────────┤ (Shared singleton)
│   │                                │
│   └─▶ services/schemas.py          │
│                                    │
└─▶ services/user_service.py         │
    │                                │
    ├─▶ services/config.py ──────────┘
    │
    └─▶ services/schemas.py

┌─────────────────────────────────────────────────────────────────────────┐
│  KEY OBSERVATIONS:                                                      │
│  1. config.py is the ONLY module that reads JSON files                 │
│  2. All services import config.py (singleton pattern)                  │
│  3. schemas.py is standalone (only depends on Pydantic)                │
│  4. JSON files are read ONCE on first get_config() call                │
│  5. No circular dependencies - clean architecture!                     │
└─────────────────────────────────────────────────────────────────────────┘
```

---

# Database Schema Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                       DATABASE RELATIONSHIPS                            │
└─────────────────────────────────────────────────────────────────────────┘

         ┌──────────────────┐
         │      users       │
         ├──────────────────┤
         │ id (PK)          │
         │ email (UNIQUE)   │
         │ password_hash    │
         │ total_exams_taken│ ← Cold-start counter (O(1) access)
         │ created_at       │
         └──────────────────┘
                 │
                 │ 1
                 │
        ┌────────┴────────────────────────────┐
        │                                     │
        │ *                                   │ *
        ▼                                     ▼
┌──────────────────┐                  ┌──────────────────┐
│  student_state   │                  │  exam_sessions   │
├──────────────────┤                  ├──────────────────┤
│ user_id (FK)     │                  │ id (PK)          │
│ mapping_id       │                  │ user_id (FK)     │
│ language_id      │                  │ language_id      │
│ mastery_score    │                  │ major_topic_id   │
│ fluency_score    │                  │ overall_score    │
│ confidence_score │                  │ difficulty       │
│ last_practiced_at│                  │ time_taken       │
│ last_updated     │                  │ created_at       │
└──────────────────┘                  └──────────────────┘
UNIQUE (user_id,                              │
        mapping_id,                           │ 1
        language_id)                          │
                                              │
    Composite PK ensures                      │ *
    one record per                            ▼
    user-topic-language              ┌──────────────────┐
    combination                      │  exam_details    │
                                     ├──────────────────┤
                                     │ session_id (FK)  │
                                     │ questions_snapshot│ ← JSONB with error_type tracking
                                     │ recommendations  │
                                     │ synergy_applied  │
                                     └──────────────────┘

┌─────────────────────────────────────────────────────────────────────────┐
│  QUERY PATTERNS:                                                        │
│                                                                         │
│  Get current mastery (with decay):                                     │
│    SELECT mastery_score, last_practiced_at                             │
│    FROM student_state                                                   │
│    WHERE user_id=:u AND language_id=:l AND mapping_id=:m               │
│    → Apply decay: score × e^(-0.02 × days)                             │
│                                                                         │
│  Update mastery (upsert):                                              │
│    INSERT INTO student_state (user_id, mapping_id, language_id, ...)   │
│    VALUES (:u, :m, :l, :score, ...)                                    │
│    ON CONFLICT (user_id, mapping_id, language_id)                      │
│    DO UPDATE SET mastery_score = EXCLUDED.mastery_score, ...           │
│                                                                         │
│  Apply synergy (language-scoped):                                      │
│    UPDATE student_state                                                │
│    SET mastery_score = LEAST(mastery_score + :bonus, 1.0)              │
│    WHERE user_id=:u AND mapping_id=:target AND language_id=:l          │
│    ↑ language_id prevents cross-language contamination!                │
│                                                                         │
│  Get previous errors (for remediation):                                │
│    SELECT ed.questions_snapshot                                        │
│    FROM exam_details ed                                                │
│    JOIN exam_sessions es ON ed.session_id = es.id                      │
│    WHERE es.user_id=:u AND es.language_id=:l                           │
│    ORDER BY es.created_at DESC LIMIT 1                                 │
│    → Extract error_type from JSONB                                     │
│                                                                         │
│  Cold-start check (O(1)):                                              │
│    SELECT total_exams_taken FROM users WHERE id=:u                     │
│    → No expensive COUNT(*) queries!                                    │
│    → session_confidence = 1 - 1/(total_exams + 1)                      │
└─────────────────────────────────────────────────────────────────────────┘
```

---

# Summary: Complete System Flow

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    END-TO-END REQUEST FLOW                              │
└─────────────────────────────────────────────────────────────────────────┘

1. FRONTEND SENDS REQUEST
   ↓
2. FASTAPI ROUTE RECEIVES
   ↓
3. PYDANTIC VALIDATES (schemas.py)
   ↓
4. SERVICE PROCESSES (grading/state_vector/user)
   │
   ├─▶ Loads config singleton (ONCE)
   │   └─▶ Reads JSON files (ONCE)
   │       └─▶ Builds indices (ONCE)
   │
   ├─▶ Queries PostgreSQL
   │   ├─▶ Read current state
   │   ├─▶ Apply business logic
   │   └─▶ Write updates (transactional)
   │
   └─▶ Uses transition_map rules
       ├─▶ Decay rates
       ├─▶ Synergy bonuses
       ├─▶ Transfer coefficients
       ├─▶ Soft gate penalties
       └─▶ Interdependency boosts
   ↓
5. PYDANTIC VALIDATES RESPONSE (schemas.py)
   ↓
6. FASTAPI RETURNS JSON
   ↓
7. FRONTEND UPDATES UI

┌─────────────────────────────────────────────────────────────────────────┐
│  CRITICAL DESIGN PATTERNS:                                              │
│                                                                         │
│  ✓ Singleton config (loaded once, shared everywhere)                   │
│  ✓ Pydantic validation (automatic, declarative)                        │
│  ✓ Database transactions (atomic updates, rollback on error)           │
│  ✓ Language scoping (prevents cross-language contamination)            │
│  ✓ Dynamic dimensions (adapts to curriculum changes)                   │
│  ✓ Exponential decay (time-based knowledge degradation)                │
│  ✓ EMA updates (smooth, stable mastery progression)                    │
│  ✓ Cold-start signals (session_confidence, performance_velocity)       │
│  ✓ Error remediation (rewards learning from mistakes)                  │
│  ✓ Bidirectional reinforcement (concept interdependencies)             │
└─────────────────────────────────────────────────────────────────────────┘
```

---

**End of System Workflow Documentation**
