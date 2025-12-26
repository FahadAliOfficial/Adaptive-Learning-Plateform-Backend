# Transition Map Configuration - Complete Guide

**Version:** 4.0  
**File:** `core/transition_map.json`  
**Purpose:** Comprehensive rules engine for knowledge transfer, decay, synergies, and prerequisite enforcement

---

## Table of Contents

1. [Global Configuration](#step-1-global-configuration)
2. [Experience Levels](#step-2-experience-levels)
3. [Universal Transitions](#step-3-universal-transitions)
4. [Intra-Language Synergy](#step-4-intra-language-synergy)
5. [Cross-Language Transfer](#step-5-cross-language-transfer)
6. [Mapping-Specific Transfer](#step-6-mapping-specific-cross-language-transfer)
7. [Soft Gates](#step-7-soft-gates)

---

# STEP 1: Global Configuration

## What is it?
Global settings that control knowledge retention, decay, and review mechanics across the entire system.

## Fields:

### `decay_rate_per_day: 0.02`

**What it is:** Daily knowledge decay rate (exponential)

**Formula:**
```
decayed_mastery = original_mastery × e^(-λ × days_passed)
where λ = 0.02
```

**Example Timeline:**

| Day | Original | Days Passed | Calculation | Decayed | Status |
|-----|----------|-------------|-------------|---------|--------|
| 0 | 0.80 | 0 | 0.80 × e^(-0.02×0) = 0.80 × 1.000 | **0.800** | ✅ Fresh |
| 5 | 0.80 | 5 | 0.80 × e^(-0.02×5) = 0.80 × 0.905 | **0.724** | ✅ Good |
| 10 | 0.80 | 10 | 0.80 × e^(-0.02×10) = 0.80 × 0.819 | **0.655** | ⚠️ At threshold |
| 15 | 0.80 | 15 | 0.80 × e^(-0.02×15) = 0.80 × 0.741 | **0.593** | 🔴 Needs review! |
| 30 | 0.80 | 30 | 0.80 × e^(-0.02×30) = 0.80 × 0.549 | **0.439** | 🔴 Critical! |

**Used where:**
- `state_vector_service.py` → `_get_decayed_mastery()`
- Accessed via: `config.get_decay_rate()`

**Why 0.02?**
- Stays above threshold for ~10 days
- Encourages weekly review
- Mirrors real cognitive decay research

**Implementation:**
```python
# state_vector_service.py
days_passed = (now - last_date).days
decay_factor = math.exp(-self.lambda_decay * days_passed)
decayed_value = score * decay_factor
```

---

### `review_multiplier: 1.5`

**What it is:** Boost applied when reviewing old topics

**Status:** ⏳ Not implemented yet (Phase 2 feature)

**Planned use:** When a student reviews a forgotten topic, they get 1.5× mastery gain

**Example Scenario:**

**Without Review Multiplier:**
```
Student reviews UNIV_LOOP (decayed to 0.58)
Accuracy: 0.75
Difficulty: 0.6
Performance: 0.75 × 0.6 = 0.45

New Mastery:
= (0.58 × 0.7) + (0.45 × 0.3)
= 0.406 + 0.135
= 0.541  ← Still below threshold!
```

**With Review Multiplier (1.5×):**
```
Performance: 0.45 × 1.5 = 0.675  ← Boosted!

New Mastery:
= (0.58 × 0.7) + (0.675 × 0.3)
= 0.406 + 0.203
= 0.609  ← Back to safe zone!
```

**Why 1.5?**
- Psychology: Rewards students for reviewing (positive reinforcement)
- Efficiency: Faster recovery = less frustration
- Research-backed: Spaced repetition studies show 1.3-1.8× effectiveness

---

### `maintenance_threshold: 0.65`

**What it is:** Minimum mastery score before a topic is considered "at risk"

**Color-Coded System:**
```
0.00 - 0.40  🔴 CRITICAL   (Forgotten / needs re-learning)
0.40 - 0.65  🟡 AT RISK    (Needs review soon)
0.65 - 0.85  🟢 SOLID      (Maintenance mode)
0.85 - 1.00  🟣 MASTERED   (Expert level)
```

**Why 0.65?**
- Based on Bloom's Taxonomy and educational research
- < 65% = Below passing grade (most education systems)
- ≥ 65% = Demonstrates competency
- ≥ 85% = Mastery level

**Used where:**

#### A. In Recommendations (Grading Service)
```python
if score < self.config.get_maintenance_threshold():  # 0.65
    days_ago = (datetime.now(timezone.utc) - last_date).days
    needs_review.append(f"{mapping_id} (last practiced {days_ago} days ago)")
```

#### B. In State Vector Metadata
```python
if mastery < 0.65:
    needs_review.append({
        "mapping_id": mapping_id,
        "current_mastery": mastery,
        "target_mastery": 0.65,
        "gap": round(0.65 - mastery, 3)
    })
```

#### C. In Gate Readiness Calculation
```python
above_threshold = sum(1 for s in mastery_scores if s >= 0.65)
total_learned = len([s for s in mastery_scores if s > 0.0])
gate_readiness = above_threshold / total_learned if total_learned > 0 else 0.0
```

---

## How All Three Work Together:

**Student Journey Example:**

**Day 0:**
```
UNIV_VAR mastery: 0.80
last_practiced_at: 2025-12-01
```

**Day 10 (Dec 11) - No Practice:**
```
Decayed Mastery: 0.80 × e^(-0.02×10) = 0.655
Status: Exactly at threshold (0.65)
System: "⚠️ UNIV_VAR needs review soon"
```

**Day 15 (Dec 16) - Student Reviews:**
```
Decayed Mastery: 0.593 (below threshold!)
Student takes review exam: 80% accuracy

WITH review_multiplier (1.5×):
New mastery: 0.682 (back above threshold!)

Database updates:
mastery_score: 0.682
last_practiced_at: 2025-12-16
```

**Configuration Philosophy:**

These three values create a **self-regulating system**:

1. **Decay (0.02)** → Creates urgency to review
2. **Threshold (0.65)** → Defines what "safe" means
3. **Review Multiplier (1.5)** → Rewards timely reviews

Together they create a **spaced repetition loop**:
```
Learn → Master (0.80+) → Time passes → Decay (0.65) → 
Alert student → Review → Boost (1.5×) → Back to mastery → Repeat
```

---

# STEP 2: Experience Levels

## What is it?
User registration priming - initializes students at different starting points based on self-reported experience.

## Structure:

```json
"experience_levels": {
  "beginner": { ... },
  "intermediate": { ... },
  "advanced": { ... }
}
```

## Three Levels:

### **Beginner**
```json
{
  "starting_mapping_id": "UNIV_SYN_LOGIC",
  "initial_mastery_estimate": 0.0,
  "initial_difficulty_tier": "beginner",
  "assumed_mastered": []
}
```

- **Starts from:** Topic 1 (Program execution basics)
- **Prior knowledge:** None (0.0 mastery)
- **Pre-populated topics:** None
- **Use case:** Complete beginners, no programming experience

---

### **Intermediate**
```json
{
  "starting_mapping_id": "UNIV_LOOP",
  "initial_mastery_estimate": 0.65,
  "initial_difficulty_tier": "beginner",
  "assumed_mastered": [
    "UNIV_SYN_LOGIC",
    "UNIV_SYN_PREC",
    "UNIV_VAR",
    "UNIV_COND"
  ]
}
```

- **Starts from:** Topic 5 (Iteration/Loops)
- **Prior knowledge:** 0.65 mastery on basics
- **Pre-populated topics:** 4 topics (Syntax, Variables, Conditionals)
- **Use case:** Some programming experience, knows basics

**What happens on registration:**
```python
# user_service.py
for mapping_id in assumed_mastered:
    insert_state = text("""
        INSERT INTO student_state 
        (user_id, mapping_id, language_id, mastery_score, fluency_score, confidence_score)
        VALUES (:user_id, :mapping_id, :language_id, 0.65, 1.2, 0.5)
    """)
```

**Result:** Database pre-populated with 4 rows showing 0.65 mastery!

---

### **Advanced**
```json
{
  "starting_mapping_id": "UNIV_OOP",
  "initial_mastery_estimate": 0.80,
  "initial_difficulty_tier": "intermediate",
  "assumed_mastered": [
    "UNIV_SYN_LOGIC", "UNIV_SYN_PREC", "UNIV_VAR",
    "UNIV_COND", "UNIV_LOOP", "UNIV_FUNC", "UNIV_COLL"
  ]
}
```

- **Starts from:** Topic 8 (Object-Oriented Programming)
- **Prior knowledge:** 0.80 mastery on all fundamentals
- **Pre-populated topics:** 7 topics (everything except OOP)
- **Use case:** Experienced programmers, want to learn OOP or new language

---

## Used where:
- `user_service.py` → `register_user()` - reads this config
- `config.py` → `get_experience_config(level)`
- Database initialization - inserts rows into `student_state` for assumed topics

---

# STEP 3: Universal Transitions - Topic-to-Topic Knowledge Transfer

## What is it?
Defines how well knowledge **transfers sequentially** from one topic to the next in the learning path.

## Structure:

```json
{
  "transition_id": "TRANS_VAR_TO_COND",
  "source_mapping_id": "UNIV_VAR",
  "target_mapping_id": "UNIV_COND",
  "transfer_coefficient": 0.75,
  "rationale": "Conditionals rely heavily on mastery of boolean types..."
}
```

## The 7 Universal Transitions:

| # | Source → Target | Coefficient | Meaning |
|---|----------------|-------------|---------|
| 1 | `UNIV_SYN_LOGIC` → `UNIV_SYN_PREC` | **0.90** | Understanding execution flow directly helps with syntax rules |
| 2 | `UNIV_SYN_PREC` → `UNIV_VAR` | **0.85** | Syntax precision is foundation for variable declaration |
| 3 | `UNIV_VAR` → `UNIV_COND` | **0.75** | Variables are used IN conditionals (boolean types) |
| 4 | `UNIV_COND` → `UNIV_LOOP` | **0.80** | Loops ARE repeated conditionals |
| 5 | `UNIV_LOOP` → `UNIV_FUNC` | **0.60** | **LOWEST** - Functions add NEW complexity (scope) |
| 6 | `UNIV_FUNC` → `UNIV_COLL` | **0.70** | Functions manipulate collections |
| 7 | `UNIV_COLL` → `UNIV_OOP` | **0.65** | Objects are complex data structures |

---

## Deep Dive Examples:

### **HIGHEST Transfer (0.90) - SYN_LOGIC → SYN_PREC**

**Why 0.90 (very high)?**

**Student learns in UNIV_SYN_LOGIC (Topic 1):**
- How programs execute line-by-line
- What a statement is
- Basic program structure
- Entry points (main function)

**When they move to UNIV_SYN_PREC (Topic 2):**
- They already understand WHAT a statement is (from Topic 1)
- Now they just learn HOW to write it correctly (semicolons, indentation)
- **90% of the hard work is done!**

**Real-world example:**
```python
# They learned this concept in SYN_LOGIC:
print("Hello")  # <-- They know this executes

# In SYN_PREC, they just learn the RULES:
print("Hello")  # ✓ Correct indentation
    print("Hello")  # ✗ Wrong indentation (but they understand what print DOES)
```

---

### **LOWEST Transfer (0.60) - LOOP → FUNC**

**Why 0.60 (lower)?**

**Student mastered UNIV_LOOP:**
```python
# They can write loops
for i in range(10):
    print(i)
```

**When they move to UNIV_FUNC:**
```python
# NEW concepts (NOT in loops):
def calculate(x, y):  # ← What's "def"? What are parameters?
    result = x + y    # ← What's scope? Is 'result' global?
    return result     # ← What's "return"?

total = calculate(5, 3)  # ← How does data flow?
```

**New complexity added:**
- **Scope** (local vs global variables) - completely new!
- **Parameters** - data passing mechanism
- **Return values** - data flowing OUT of functions
- **Call stack** - execution context

**Only 60% transfers because:**
- Control flow knowledge (from loops) helps: 40%
- Variable usage (from loops) helps: 20%
- But 40% is COMPLETELY NEW (scope, parameters, returns)

---

## Status: Phase 2 Feature

Currently, `universal_transitions` is **DEFINED but NOT USED** in your code.

**Planned Implementation: Adaptive Difficulty Reduction**

```python
# Future implementation in grading_service.py

def _calculate_effective_difficulty(self, user_id, target_mapping_id, base_difficulty):
    # Find the transition TO this target topic
    transition = find_transition(target_mapping_id)
    
    # Get source topic mastery
    source_mastery = self._get_mastery(user_id, transition['source_mapping_id'])
    transfer_coefficient = transition['transfer_coefficient']
    
    # Formula: Higher source mastery + high transfer = EASIER target
    difficulty_reduction = source_mastery * transfer_coefficient
    effective_difficulty = base_difficulty * (1 - (difficulty_reduction * 0.3))
    
    return max(effective_difficulty, 0.3)  # Minimum difficulty
```

**Example:**
```
Student learning UNIV_COND (Conditionals)
Base difficulty: 0.75
Source mastery (UNIV_VAR): 0.85
Transfer coefficient: 0.75

Calculation:
difficulty_reduction = 0.85 × 0.75 = 0.6375
effective_difficulty = 0.75 × (1 - 0.191) = 0.607 ← 19% easier!
```

---

# STEP 4: Intra-Language Synergy - Bidirectional Knowledge Reinforcement

## What is it?
Defines how mastering one topic **automatically boosts** related topics you've already learned within the SAME language.

**Status:** ✅ **FULLY IMPLEMENTED**

## Structure:

```json
{
  "trigger_mapping_id": "UNIV_LOOP",
  "target_mapping_id": "UNIV_COND",
  "synergy_bonus": 0.08,
  "description": "Practicing loops reinforces conditional logic understanding"
}
```

## All 5 Synergy Relationships:

| # | When You Master... | It Boosts... | Bonus | Why? |
|---|-------------------|-------------|--------|------|
| 1 | `UNIV_LOOP` | `UNIV_COND` | **+0.08** | Loop conditions use boolean logic |
| 2 | `UNIV_FUNC` | `UNIV_VAR` | **+0.10** | Function parameters deepen variable understanding |
| 3 | `UNIV_COLL` | `UNIV_LOOP` | **+0.12** (HIGHEST) | Iterating collections heavily uses loops |
| 4 | `UNIV_OOP` | `UNIV_COLL` | **+0.05** | Objects manage data like collections |
| 5 | `UNIV_OOP` | `UNIV_FUNC` | **+0.07** | Methods deepen function concepts |

---

## Real Implementation:

```python
# grading_service.py → _apply_synergy()

def _apply_synergy(self, user_id: str, language_id: str, source_mapping_id: str) -> List[str]:
    bonuses = self.config.get_synergy_bonuses(source_mapping_id)
    applied = []
    
    for bonus in bonuses:
        target_id = bonus['target_mapping_id']
        bonus_value = bonus['synergy_bonus']
        
        # SQL UPDATE: Add bonus to target topic's mastery
        sql = text("""
            UPDATE student_state 
            SET mastery_score = LEAST(mastery_score + :val, 1.0)
            WHERE user_id=:u 
              AND mapping_id=:target 
              AND language_id=:l  ← SAME LANGUAGE ONLY!
        """)
        
        result = self.db.execute(sql, {"val": bonus_value, "u": user_id, "target": target_id, "l": language_id})
        
        if result.rowcount > 0:
            applied.append(f"{target_id} (+{bonus_value})")
    
    return applied
```

---

## Example Scenario: The Synergy Chain

**Student's Current State:**
```
Python UNIV_COND: 0.72
Python UNIV_LOOP: 0.58
Python UNIV_VAR: 0.68
```

**Event: Student Takes Python UNIV_LOOP Exam**
- Accuracy: 85% (excellent!)
- Triggers synergy (≥70% threshold)

**Processing:**

1. **Update UNIV_LOOP mastery:** 0.58 → 0.559 (via EMA)
2. **Check synergies triggered by UNIV_LOOP:** Found `UNIV_LOOP → UNIV_COND (+0.08)`
3. **Apply boost to UNIV_COND:** 0.72 + 0.08 = **0.80** ✅

**Final State:**
```
Python UNIV_COND: 0.72 → 0.80 (FREE +0.08 boost!)
Python UNIV_LOOP: 0.58 → 0.559 (updated)
Python UNIV_VAR: 0.68 (no change)
```

**API Response:**
```json
{
  "synergies_applied": ["UNIV_COND (+0.08)"],
  "recommendations": [
    "🎉 Great work! Practicing loops reinforced your conditional logic!",
    "📈 UNIV_COND boosted from 0.72 → 0.80"
  ]
}
```

---

## Why Each Synergy Exists:

### **Synergy #3: COLL → LOOP (+0.12) - HIGHEST!**

**Cognitive Connection:**
```python
# Almost impossible to use collections without loops!
my_list = [1, 2, 3, 4, 5]

for item in my_list:  # ← Loop iteration
    print(item)

# Even "hidden" loops:
squares = [x**2 for x in my_list]  # ← List comprehension (loop)
```

**Learning Effect:**
- Collections are USELESS without iteration
- Every collection operation practices loop patterns
- Students iterate hundreds of times when learning collections

**Bonus Size (0.12):** HIGHEST - near-mandatory connection

---

## Why 70% Accuracy Threshold?

```python
if accuracy >= 0.7:
    synergies_applied = self._apply_synergy(...)
```

**Educational Reasoning:**

- **70% (0.7) = Mastery Threshold**
- Below 70%: Student is still learning, struggling
- Above 70%: Student demonstrates competency
- Bloom's Taxonomy: 70% = "Application" level

**Why NOT trigger below 70%?**
```
Example: Student gets 50% on UNIV_LOOP exam
- They're struggling with loops themselves
- Don't boost UNIV_COND - they haven't mastered the connection
- Focus on IMPROVING loops first
```

---

## CRITICAL: Language Isolation

**Synergies are LANGUAGE-SCOPED!**

```sql
WHERE user_id=:u AND mapping_id=:target AND language_id=:l
```

**Example:**
```
Student completes Python UNIV_LOOP exam (85%)
  ↓
Boosts: Python UNIV_COND (+0.08)
Does NOT boost: JavaScript UNIV_COND (isolated!)
```

**Why this is correct:**
- Python syntax ≠ JavaScript syntax
- No false positives
- Student must earn synergies per language

---

# STEP 5: Cross-Language Transfer - Language-to-Language Knowledge Transfer

## What is it?
Defines how well programming knowledge transfers when a student learns a **second language** after mastering a first one.

**Status:** ✅ **FULLY IMPLEMENTED**

## Structure:

```json
{
  "transfer_id": "PYTHON_TO_JAVASCRIPT",
  "source_language_id": "python_3",
  "target_language_id": "javascript_es6",
  "logic_acceleration": 0.88,
  "syntax_friction": -0.15,
  "note": "Similar high-level abstractions; main friction is braces vs indentation"
}
```

---

## Fields Explained:

### **`logic_acceleration` - Conceptual Transfer**

**What it means:** Percentage of conceptual knowledge that transfers  
**Range:** 0.65 to 0.98 (65% to 98%)

### The Spectrum (20 Total Transfers):

| From → To | Logic Acceleration | Meaning |
|-----------|-------------------|---------|
| **C++ → Java** | **0.98** (HIGHEST!) | C++ mastery makes Java trivial |
| **C++ → Python** | **0.95** | Massive conceptual overlap |
| **Java → Python** | **0.92** | Strong transfer, less verbosity |
| **JavaScript → Python** | **0.90** | Very smooth transition |
| **C++ → JavaScript** | **0.88** | High-level abstractions feel easy |
| **Python → JavaScript** | **0.88** | Similar abstractions |
| **Python → Java** | **0.85** | Good transfer despite typing differences |
| **JavaScript → Java** | **0.78** | Moderate transfer, typing friction |
| **Python → Go** | **0.75** | Decent transfer, different paradigms |
| **Python → C++** | **0.70** (LOWEST for Python) | Significant new concepts |
| **JavaScript → C++** | **0.65** (OVERALL LOWEST!) | Huge conceptual gap |

---

### **`syntax_friction` - Language Barrier Penalty**

**What it means:** Difficulty penalty/bonus due to syntax differences  
**Range:** -0.55 to +0.40

- **Negative = Harder** (friction, obstacles)
- **Positive = Easier** (acceleration, relief)

### Most Friction (Hardest Transitions):

| From → To | Friction | Why? |
|-----------|----------|------|
| **JavaScript → C++** | **-0.55** | Memory management, pointers, compilation |
| **Python → C++** | **-0.50** | Manual memory, pointers, complexity |
| **Go → C++** | **-0.45** | Memory management gap |
| **Java → C++** | **-0.40** | Manual memory is the barrier |

### Least Friction / Positive Acceleration:

| From → To | Friction | Why? |
|-----------|----------|------|
| **C++ → Python** | **+0.40** (HIGHEST!) | Python feels liberating! |
| **C++ → Java** | **+0.35** | Java feels safer, simpler |
| **C++ → Go** | **+0.30** | Garbage collection relief |
| **C++ → JavaScript** | **+0.30** | High-level abstractions are easy |
| **Java → Python** | **+0.25** | Reduced boilerplate |

---

## Real Implementation:

```python
# grading_service.py → _apply_cross_language_transfer()

def _apply_cross_language_transfer(self, user_id, current_language, mapping_id, new_mastery):
    # Get mastery in OTHER languages
    other_langs_query = text("""
        SELECT language_id, mastery_score
        FROM student_state
        WHERE user_id = :u 
          AND mapping_id = :m
          AND language_id != :current_lang  ← OTHER languages!
          AND mastery_score > 0.5
    """)
    
    other_langs = self.db.execute(other_langs_query, {...}).fetchall()
    
    for source_lang, source_mastery in other_langs:
        # Find transfer config
        transfer = find_transfer(source_lang, current_language)
        
        # Calculate boost
        logic_component = source_mastery * transfer['logic_acceleration']
        syntax_component = transfer['syntax_friction']
        raw_boost = logic_component + syntax_component
        scaled_boost = max(raw_boost * 0.2, 0.0)
        
        # Apply to database
        UPDATE student_state SET mastery_score = LEAST(mastery_score + scaled_boost, 1.0)
        WHERE language_id = current_language
```

---

## Example Calculation: C++ → Python Transfer

**Scenario:**
```
Student has mastered C++ UNIV_VAR: 0.90
Now learning Python UNIV_VAR (current: 0.35)
```

**Transfer Config:**
```json
{
  "logic_acceleration": 0.95,
  "syntax_friction": 0.40
}
```

**Calculation:**
```python
logic_component = 0.90 * 0.95 = 0.855
raw_boost = 0.855 + 0.40 = 1.255
scaled_boost = 1.255 * 0.2 = 0.251

new_mastery = 0.35 + 0.251 = 0.601
```

**Result:**
```
Python UNIV_VAR: 0.35 → 0.60 (MASSIVE boost from C++ knowledge!)
Student skips beginner phase!
```

---

## Example: Python → C++ (Opposite Direction)

**Scenario:**
```
Student has mastered Python UNIV_VAR: 0.85
Now learning C++ UNIV_VAR (current: 0.30)
```

**Transfer Config:**
```json
{
  "logic_acceleration": 0.70,
  "syntax_friction": -0.50
}
```

**Calculation:**
```python
logic_component = 0.85 * 0.70 = 0.595
raw_boost = 0.595 + (-0.50) = 0.095
scaled_boost = 0.095 * 0.2 = 0.019

new_mastery = 0.30 + 0.019 = 0.319
```

**Result:**
```
C++ UNIV_VAR: 0.30 → 0.32 (tiny boost - pointers/memory are NEW!)
Student still needs extensive C++ practice!
```

---

## Why These Numbers?

### **Highest Transfer: C++ → Java (0.98 logic, +0.35 friction)**

```cpp
// C++ code
class Student {
    private:
        string name;
    public:
        Student(string n) : name(n) {}
        string getName() { return name; }
};
```

```java
// Java code (almost identical!)
class Student {
    private String name;
    public Student(String n) { this.name = n; }
    public String getName() { return name; }
}
```

**Differences:**
- Java has garbage collection (EASIER!)
- No pointers (SAFER!)
- Similar syntax, simpler memory model

**Result:** Java feels like "C++ with training wheels"

---

### **Lowest Transfer: JavaScript → C++ (0.65 logic, -0.55 friction)**

```javascript
// JavaScript - dynamic, high-level
let numbers = [1, 2, 3, 4];
numbers.push(5);  // Easy!
```

```cpp
// C++ - manual memory, static typing
int* numbers = new int[4];  // Fixed size!
// Need to reallocate to add element!
int* temp = new int[5];
for(int i = 0; i < 4; i++) temp[i] = numbers[i];
delete[] numbers;  // Manual cleanup!
numbers = temp;
numbers[4] = 5;
```

**New Concepts:**
- Manual memory management
- Pointers and references
- Static typing
- Compilation
- Templates

**Result:** Completely different mental model!

---

# STEP 6: Mapping-Specific Cross-Language Transfer - Fine-Grained Transfer

## What is it?
Provides **topic-specific** overrides for cases where certain concepts transfer better/worse than the general language transfer rate.

## Structure:

```json
{
  "mapping_id": "UNIV_VAR",
  "source_language_id": "python_3",
  "target_language_id": "go_1_21",
  "acceleration_factor": 0.40,
  "note": "Lower acceleration due to dynamic→static typing + pointers"
}
```

## Why This Exists:

**Problem:** Not all topics transfer equally!

**Example:**
```
Python → JavaScript (overall): 0.88 logic_acceleration

BUT:
- UNIV_LOOP (Python → JS): 0.90 (very similar!)
- UNIV_VAR (Python → Go): 0.40 (very different!)
```

---

## All Topic-Specific Overrides (14 Total):

| Topic | From → To | Factor | Why Different? |
|-------|-----------|--------|----------------|
| **UNIV_VAR** | Python → Go | **0.40** | Dynamic → static typing is HARD |
| **UNIV_VAR** | Java → C++ | **0.88** | Static typing transfers well, pointers add complexity |
| **UNIV_LOOP** | JS → Python | **0.90** | for-of ≈ for-in (nearly identical) |
| **UNIV_LOOP** | Python → JS | **0.88** | Very similar iteration patterns |
| **UNIV_FUNC** | JS → Python | **0.85** | First-class functions transfer well |
| **UNIV_FUNC** | Go → JS | **0.82** | Function patterns similar |
| **UNIV_COLL** | Python → JS | **0.88** | Lists/dicts map to arrays/objects |
| **UNIV_COLL** | Java → C++ | **0.75** | Collections → STL, but memory differs |
| **UNIV_OOP** | C++ → Java | **0.95** | C++ OOP makes Java OOP trivial |
| **UNIV_OOP** | Java → C++ | **0.92** | Strong OOP foundation transfers |
| **UNIV_OOP** | Python → Java | **0.70** | Duck typing → strict typing is hard |
| **UNIV_COND** | JS → Python | **0.92** | Conditional logic is universal |
| **UNIV_SYN_LOGIC** | C++ → Java | **0.92** | Compilation concepts transfer |
| **UNIV_SYN_PREC** | C++ → Java | **0.95** | C++ syntax mastery simplifies Java |

---

## How It's Used:

```python
# grading_service.py

# First, check for mapping-specific override
specific_transfer = find_specific_transfer(mapping_id, source_lang, target_lang)

if specific_transfer:
    # Use specific acceleration_factor
    boost = source_mastery * specific_transfer['acceleration_factor'] * 0.2
else:
    # Use general cross_language_transfer config
    boost = (source_mastery * logic_acceleration + syntax_friction) * 0.2
```

---

# STEP 7: Soft Gates - Prerequisite Enforcement

## What is it?
Defines **critical checkpoints** where students MUST have solid prerequisite knowledge before tackling advanced topics.

**Status:** ✅ **FULLY IMPLEMENTED**

## Structure:

```json
{
  "gate_id": "GATE_OOP_MASTERY",
  "mapping_id": "UNIV_OOP",
  "prerequisite_mappings": ["UNIV_VAR", "UNIV_FUNC", "UNIV_COLL"],
  "ideal_mastery_score": 0.80,
  "minimum_allowable_score": 0.60,
  "penalty_steepness": 2.5,
  "description": "OOP requires strong foundations in variables, functions, and collections"
}
```

## 3 Gates Defined:

| Gate | Topic | Prerequisites | Min Score | Penalty |
|------|-------|---------------|-----------|---------|
| **GATE_OOP_MASTERY** | UNIV_OOP | VAR, FUNC, COLL | 0.60 | 2.5 (HARSHEST) |
| **GATE_FUNC_MASTERY** | UNIV_FUNC | VAR, COND, LOOP | 0.55 | 2.0 |
| **GATE_COLL_MASTERY** | UNIV_COLL | VAR, LOOP | 0.58 | 2.2 |

---

## Field Breakdown:

### **`ideal_mastery_score` vs `minimum_allowable_score`**

```
ideal_mastery_score: 0.80    ← Target prerequisite mastery
minimum_allowable_score: 0.60 ← Below this = severe penalty

Scoring Zones:
0.80+     : No penalty (prerequisites met!)
0.60-0.80 : Partial penalty (learning is harder)
< 0.60    : SEVERE penalty (knowledge gaps will cause failure)
```

---

### **`penalty_steepness` - The Learning Handicap**

**Formula:**
```python
penalty_factor = math.exp(-penalty_steepness)
```

**What it means:**

| Steepness | Penalty Factor | Effect |
|-----------|----------------|--------|
| **2.5** (OOP) | e^(-2.5) = **0.082** | **91.8% penalty!** |
| **2.2** (COLL) | e^(-2.2) = **0.111** | **88.9% penalty** |
| **2.0** (FUNC) | e^(-2.0) = **0.135** | **86.5% penalty** |

---

## Real Implementation:

```python
# grading_service.py → _check_soft_gates()

def _check_soft_gates(self, user_id, language_id, mapping_id):
    gate = self.config.get_soft_gate(mapping_id)
    
    if not gate:
        return []
    
    violations = []
    prereq_mappings = gate['prerequisite_mappings']
    min_required = gate['minimum_allowable_score']
    
    for prereq in prereq_mappings:
        result = db.execute("""
            SELECT mastery_score FROM student_state
            WHERE user_id=:u AND mapping_id=:m AND language_id=:l
        """)
        
        if not result:
            violations.append(f"{prereq} (not started)")
        elif result[0] < min_required:
            violations.append(f"{prereq} (mastery: {result[0]:.2f} < {min_required})")
    
    return violations
```

---

### **Penalty Application:**

```python
# In _update_mastery()

if has_violations:
    gate = self.config.get_soft_gate(mapping_id)
    penalty_factor = math.exp(-gate['penalty_steepness'])
    performance *= penalty_factor  # Massive reduction!

# Example:
# Student scores 80% on OOP exam
# But prerequisites are weak
# performance = 0.80 * 0.082 = 0.0656 ← Treated as 6.5% score!
```

---

## Example Scenario: Student Attempts UNIV_OOP Too Early

**Prerequisites (GATE_OOP_MASTERY):**
```
- UNIV_VAR: 0.45 (< 0.60 required)  ❌
- UNIV_FUNC: 0.52 (< 0.60 required) ❌
- UNIV_COLL: 0.38 (< 0.60 required) ❌
```

**Exam Performance:**
```
Raw accuracy: 75%
Raw difficulty: 0.7
Raw performance: 0.75 * 0.7 = 0.525
```

**Penalty Applied:**
```python
penalty_factor = e^(-2.5) = 0.082
penalized_performance = 0.525 * 0.082 = 0.043
```

**Mastery Update:**
```python
new_mastery = (0.00 * 0.7) + (0.043 * 0.3) = 0.013
```

**Result:** Basically learned NOTHING despite 75% accuracy!

---

**API Response:**
```json
{
  "success": true,
  "accuracy": 0.75,
  "new_mastery_score": 0.013,
  "soft_gate_violations": [
    "UNIV_VAR (mastery: 0.45 < 0.60)",
    "UNIV_FUNC (mastery: 0.52 < 0.60)",
    "UNIV_COLL (mastery: 0.38 < 0.60)"
  ],
  "recommendations": [
    "⚠️ Prerequisites not met for UNIV_OOP!",
    "📚 Master UNIV_VAR, UNIV_FUNC, UNIV_COLL first",
    "🔙 Review foundational topics before continuing"
  ]
}
```

---

## Summary Table: All Mechanisms

| Mechanism | Scope | Trigger | Status | Purpose |
|-----------|-------|---------|--------|---------|
| **Config** | Global | Always active | ✅ Implemented | Knowledge decay, thresholds |
| **Experience Levels** | User registration | One-time | ✅ Implemented | Initial state priming |
| **Universal Transitions** | Sequential topics | Moving to next topic | ⏳ Phase 2 | Reduce difficulty |
| **Intra-Language Synergy** | Same language | Complete exam (70%+) | ✅ Implemented | Boost related topics |
| **Cross-Language Transfer** | Across languages | First practice in new language | ✅ Implemented | Transfer conceptual knowledge |
| **Mapping-Specific Transfer** | Topic-specific | Same as above | ✅ Implemented | Fine-tuned transfer rates |
| **Soft Gates** | Prerequisites | Attempting advanced topic | ✅ Implemented | Enforce learning order |

---

# STEP 8: Language-Specific Modifiers - Per-Language Difficulty Adjustments

## What is it?
Overrides the base difficulty for specific topics in specific languages, accounting for language-unique complexity.

**Status:** ⏳ **NOT IMPLEMENTED** (Phase 2 feature)

## Structure:

```json
{
  "language_id": "cpp_20",
  "mapping_id": "UNIV_VAR",
  "difficulty_multiplier": 1.4,
  "reason": "Pointers and manual memory concepts significantly increase complexity"
}
```

## All 6 Modifiers Defined:

| Language | Topic | Multiplier | Effect | Reason |
|----------|-------|------------|--------|--------|
| **C++ 20** | UNIV_VAR | **1.4** | +40% harder | Pointers, manual memory management |
| **C++ 20** | UNIV_OOP | **1.3** | +30% harder | Multiple inheritance, virtual functions, destructors |
| **Java 17** | UNIV_OOP | **1.2** | +20% harder | Strict OOP with interfaces and abstract classes |
| **Python 3** | UNIV_SYN_PREC | **0.8** | 20% easier | Indentation-based syntax is more intuitive |
| **JavaScript ES6** | UNIV_FUNC | **1.15** | +15% harder | Closures, hoisting, callback patterns |
| **Go 1.21** | UNIV_OOP | **0.9** | 10% easier | Composition-based approach simpler than inheritance |

---

## How It Works (Planned):

### **Base Difficulty (from final_curriculum.json):**
```json
{
  "major_topic_id": "PY_VAR_01",
  "mapping_id": "UNIV_VAR",
  "global_difficulty": 0.10
}
```

### **Modified Difficulty (when language_id = cpp_20):**
```python
base_difficulty = 0.10  # From curriculum
modifier = 1.4          # From language_specific_modifiers

effective_difficulty = base_difficulty * modifier
# 0.10 * 1.4 = 0.14 (40% harder!)
```

---

## Real-World Examples:

### **Example 1: C++ Variables (1.4× multiplier)**

**Python Variables (base difficulty: 0.10):**
```python
x = 5           # Easy!
name = "John"   # Dynamic typing
numbers = [1, 2, 3]
```

**C++ Variables (effective difficulty: 0.14):**
```cpp
int x = 5;                    // Static typing
char* name = "John";          // Pointer!
int* numbers = new int[3];    // Manual allocation!
numbers[0] = 1;
// ... must call delete[] numbers later!
```

**New Concepts in C++:**
- Static type declarations
- Pointers (`*`)
- Manual memory allocation (`new`)
- Manual cleanup (`delete`)
- Reference vs value semantics

**Result:** 40% harder justified!

---

### **Example 2: Python Syntax (0.8× multiplier - EASIER!)**

**JavaScript Syntax (base difficulty: 0.10):**
```javascript
if (x > 5) {
    console.log("Greater");
}
// Need to remember: (), {}, ;
```

**Python Syntax (effective difficulty: 0.08):**
```python
if x > 5:
    print("Greater")
# Natural indentation, no braces!
```

**Why Easier:**
- No curly braces to manage
- No parentheses around conditions
- Indentation is intuitive (natural writing)
- No semicolons to remember

**Result:** 20% easier justified!

---

## Planned Implementation:

```python
# In grading_service.py (Phase 2)

def _get_effective_difficulty(self, language_id, mapping_id, base_difficulty):
    """
    Apply language-specific difficulty modifiers.
    """
    # Check for modifier
    for modifier in self.config.transition_map['language_specific_modifiers']:
        if (modifier['language_id'] == language_id and 
            modifier['mapping_id'] == mapping_id):
            multiplier = modifier['difficulty_multiplier']
            return base_difficulty * multiplier
    
    return base_difficulty  # No modifier, use base
```

### **Use Case:**

When generating questions or calculating mastery gains:
```python
# Question selection
base_diff = 0.10  # From curriculum
effective_diff = _get_effective_difficulty('cpp_20', 'UNIV_VAR', base_diff)
# Returns: 0.14

# Select harder questions for C++ variables
questions = select_questions(difficulty=effective_diff)
```

---

# STEP 9: Question Difficulty Tiers - Progressive Challenge System

## What is it?
Defines 3 difficulty tiers (beginner, intermediate, advanced) for each topic, with unlock thresholds and target accuracy rates.

**Status:** ✅ **PARTIALLY IMPLEMENTED** (used in `config.py → get_difficulty_tier()`)

## Structure:

```json
{
  "mapping_id": "UNIV_VAR",
  "default_for_all_languages": true,
  "tiers": {
    "beginner": {
      "weight": 0.3,
      "min_mastery_to_unlock": 0.0,
      "target_accuracy": 0.7
    },
    "intermediate": {
      "weight": 0.6,
      "min_mastery_to_unlock": 0.5,
      "target_accuracy": 0.8
    },
    "advanced": {
      "weight": 0.9,
      "min_mastery_to_unlock": 0.75,
      "target_accuracy": 0.9
    }
  }
}
```

---

## Field Breakdown:

### **`weight` - Question Difficulty Value**

This is the **difficulty score** assigned to questions in this tier.

- **Beginner:** 0.3-0.5 (easy questions)
- **Intermediate:** 0.6-0.8 (moderate questions)
- **Advanced:** 0.9-1.3 (hard questions)

**Used in:**
```python
# When processing exam results
performance = accuracy * difficulty_weight
# Harder questions (higher weight) = more credit!
```

---

### **`min_mastery_to_unlock` - Tier Gate**

Minimum mastery score required to access this tier.

**Progression Path:**

```
Mastery: 0.00-0.49  → Beginner tier only
Mastery: 0.50-0.74  → Beginner + Intermediate tiers
Mastery: 0.75+      → All tiers (including Advanced)
```

**Example:**
```python
# Student has 0.48 mastery in UNIV_VAR
tier = get_difficulty_tier('UNIV_VAR', 0.48)
# Returns: 'beginner' (can't unlock intermediate yet!)

# Student has 0.80 mastery
tier = get_difficulty_tier('UNIV_VAR', 0.80)
# Returns: 'advanced' (all tiers unlocked!)
```

---

### **`target_accuracy` - Expected Performance**

The accuracy percentage students SHOULD achieve at this tier.

**Purpose:** Used for adaptive difficulty (Phase 2)

**Logic:**
```
If actual_accuracy > target_accuracy:
    → Move to harder tier (student is ready!)

If actual_accuracy < target_accuracy:
    → Stay at current tier or move easier
```

**Example:**
```
Beginner tier (target: 70%):
- Student scores 85% → "Too easy, try intermediate!"
- Student scores 60% → "Stay at beginner, needs more practice"

Advanced tier (target: 90%):
- Student scores 92% → "Mastered!"
- Student scores 75% → "Try intermediate tier instead"
```

---

## All Tier Configurations:

### **Default Tiers (Applied to All Languages):**

| Topic | Beginner | Intermediate | Advanced |
|-------|----------|--------------|----------|
| **UNIV_VAR** | 0.3 / unlock: 0.0 / target: 70% | 0.6 / unlock: 0.5 / target: 80% | 0.9 / unlock: 0.75 / target: 90% |
| **UNIV_COND** | 0.35 / unlock: 0.0 / target: 70% | 0.65 / unlock: 0.5 / target: 80% | 0.95 / unlock: 0.75 / target: 90% |
| **UNIV_LOOP** | 0.4 / unlock: 0.0 / target: 65% | 0.7 / unlock: 0.5 / target: 75% | 1.0 / unlock: 0.7 / target: 85% |
| **UNIV_FUNC** | 0.45 / unlock: 0.0 / target: 65% | 0.75 / unlock: 0.5 / target: 75% | 1.1 / unlock: 0.7 / target: 85% |
| **UNIV_COLL** | 0.5 / unlock: 0.0 / target: 65% | 0.8 / unlock: 0.5 / target: 75% | 1.1 / unlock: 0.7 / target: 85% |
| **UNIV_OOP** | 0.6 / unlock: 0.0 / target: 60% | 0.9 / unlock: 0.45 / target: 70% | 1.3 / unlock: 0.7 / target: 85% |

### **Python-Specific Overrides:**

| Topic | Python Tier Details |
|-------|---------------------|
| **PY_SYN_LOGIC** | Beginner: 0.3, Intermediate: 0.6, Advanced: 0.9 |
| **PY_VAR_01** | Intermediate unlocks at 0.55 (easier than default 0.5) |
| **PY_FUNC_01** | Beginner: 0.4, Intermediate: 0.7, Advanced: 1.0 |
| **PY_OOP_01** | Beginner: 0.5, Intermediate: 0.8 (unlock: 0.45), Advanced: 1.2 |

---

## Current Implementation:

```python
# config.py → get_difficulty_tier()

def get_difficulty_tier(self, mapping_id: str, mastery_score: float) -> str:
    """
    Determine which difficulty tier user should practice.
    """
    for tier_config in self.transition_map['question_difficulty_tiers']:
        if tier_config.get('mapping_id') == mapping_id:
            tiers = tier_config['tiers']
            
            if mastery_score < tiers['intermediate']['min_mastery_to_unlock']:
                return 'beginner'
            elif mastery_score < tiers['advanced']['min_mastery_to_unlock']:
                return 'intermediate'
            else:
                return 'advanced'
    
    return 'intermediate'  # Default fallback
```

**Used in:**
- `grading_service.py` → `_generate_recommendations()` (suggests next tier)
- Question bank selection (Phase 2 - when implemented)

---

## Example Student Journey:

**Day 1 - Starting Out:**
```
Mastery: 0.00
Tier: Beginner
Questions: weight 0.3 (easy)
Target: 70% accuracy
```

**Day 5 - Making Progress:**
```
Mastery: 0.55
Tier: Intermediate (UNLOCKED!)
Questions: weight 0.6 (moderate)
Target: 80% accuracy
```

**Day 15 - Advanced:**
```
Mastery: 0.78
Tier: Advanced (UNLOCKED!)
Questions: weight 0.9 (hard)
Target: 90% accuracy
```

---

# STEP 10: Adaptive Difficulty Curves - Dynamic Adjustment Rules

## What is it?
Defines how the system adjusts difficulty based on recent performance windows.

**Status:** ⏳ **NOT IMPLEMENTED** (Phase 2 feature)

## Structure:

```json
{
  "description": "Dynamic difficulty adjustment based on recent learner performance",
  "performance_windows": {
    "sample_size": 10,
    "description": "Number of recent questions to evaluate performance"
  },
  "adjustment_rules": [
    {
      "accuracy_range": [0.9, 1.0],
      "difficulty_multiplier": 1.3,
      "action": "increase_difficulty",
      "description": "High accuracy - challenge the learner more"
    }
  ]
}
```

---

## Performance Windows:

**`sample_size: 10`** - System looks at the **last 10 questions** to determine adjustment.

**Example:**
```
Questions 1-10: [✓✓✓✓✓✗✓✓✓✓]
Accuracy: 90% → Trigger "increase_difficulty"

Questions 11-20: [✗✗✓✗✓✗✓✗✓✗]
Accuracy: 40% → Trigger "decrease_difficulty"
```

---

## 5 Adjustment Rules:

| Accuracy Range | Multiplier | Action | Effect |
|----------------|------------|--------|--------|
| **90-100%** | **1.3** | Increase difficulty | Too easy, challenge more! |
| **75-90%** | **1.1** | Slight increase | Good progress, gentle push |
| **60-75%** | **1.0** | Maintain | Appropriate difficulty |
| **40-60%** | **0.85** | Slight decrease | Struggling, ease up |
| **0-40%** | **0.7** | Decrease difficulty | Very hard, review prerequisites |

---

## How It Would Work:

```python
# Phase 2 implementation

def adjust_difficulty_dynamically(user_id, mapping_id):
    # Get last 10 question results
    recent = get_recent_questions(user_id, mapping_id, limit=10)
    
    # Calculate accuracy
    correct = sum(1 for q in recent if q.is_correct)
    accuracy = correct / len(recent)
    
    # Find matching rule
    for rule in adaptive_difficulty_curves['adjustment_rules']:
        min_acc, max_acc = rule['accuracy_range']
        if min_acc <= accuracy <= max_acc:
            multiplier = rule['difficulty_multiplier']
            break
    
    # Adjust next question difficulty
    current_difficulty = get_current_difficulty(user_id, mapping_id)
    new_difficulty = current_difficulty * multiplier
    
    return new_difficulty
```

---

## Example Scenario:

**Student practicing UNIV_LOOP:**

**Session 1 (Questions 1-10):**
```
Results: [✓✓✓✓✓✓✓✓✓✓]
Accuracy: 100%
Current difficulty: 0.5
Adjustment: 0.5 × 1.3 = 0.65 (harder!)
```

**Session 2 (Questions 11-20):**
```
Results: [✓✓✓✗✓✓✓✓✗✓]
Accuracy: 80%
Current difficulty: 0.65
Adjustment: 0.65 × 1.1 = 0.715 (slightly harder)
```

**Session 3 (Questions 21-30):**
```
Results: [✗✗✓✗✗✓✗✓✗✗]
Accuracy: 30%
Current difficulty: 0.715
Adjustment: 0.715 × 0.7 = 0.50 (much easier!)
Action: "Review prerequisites" warning
```

---

## Mastery Boost on Tier Completion:

```json
"mastery_boost_on_tier_completion": {
  "beginner": 0.15,
  "intermediate": 0.25,
  "advanced": 0.35
}
```

**What it means:** Bonus mastery when completing ALL questions in a tier.

**Example:**
```
Student completes beginner tier:
- Final mastery: 0.45
- Bonus: +0.15
- New mastery: 0.60 (ready for intermediate!)
```

---

# STEP 11: Temporal Learning Patterns - Time-Based Learning Estimates

## What is it?
Research-based estimates for how long each topic takes to master, including optimal session lengths.

**Status:** ⏳ **NOT IMPLEMENTED** (Phase 2 analytics feature)

## Structure:

```json
{
  "mapping_id": "UNIV_FUNC",
  "estimated_hours": 8.0,
  "min_practice_problems": 30,
  "optimal_session_length_minutes": 50,
  "sessions_to_mastery": 8
}
```

---

## All 8 Topic Estimates:

| Topic | Est. Hours | Min Problems | Session Length | Sessions | Difficulty |
|-------|------------|--------------|----------------|----------|------------|
| **UNIV_SYN_LOGIC** | 2.0 | 8 | 30 min | 3 | ⭐ Easiest |
| **UNIV_SYN_PREC** | 2.5 | 12 | 35 min | 4 | ⭐ |
| **UNIV_VAR** | 4.0 | 20 | 45 min | 5 | ⭐⭐ |
| **UNIV_COND** | 3.5 | 18 | 40 min | 5 | ⭐⭐ |
| **UNIV_LOOP** | 5.0 | 25 | 45 min | 6 | ⭐⭐⭐ |
| **UNIV_FUNC** | 8.0 | 30 | 50 min | 8 | ⭐⭐⭐⭐ |
| **UNIV_COLL** | 7.0 | 28 | 50 min | 7 | ⭐⭐⭐⭐ |
| **UNIV_OOP** | 12.0 | 40 | 60 min | 10 | ⭐⭐⭐⭐⭐ Hardest |

---

## Field Breakdown:

### **`estimated_hours`**
Total time to reach 0.80+ mastery (based on educational research)

**Total Learning Time:**
```
All 8 topics: 2 + 2.5 + 4 + 3.5 + 5 + 8 + 7 + 12 = 44 hours
Average per topic: 5.5 hours
```

---

### **`min_practice_problems`**
Minimum number of questions needed to reach mastery

**Why Different Numbers?**
- **Syntax (8-12 problems):** Straightforward, memorization-based
- **Functions (30 problems):** Complex, many patterns to practice
- **OOP (40 problems):** Most complex, inheritance/polymorphism variations

---

### **`optimal_session_length_minutes`**
Research-based ideal study session duration

**Cognitive Science Rationale:**
- **30-35 min:** Simple topics (attention span for memorization)
- **45-50 min:** Moderate topics (problem-solving focus time)
- **60 min:** Complex topics (deep cognitive processing)

**Avoid:**
- < 30 min: Too short for deep learning
- > 60 min: Diminishing returns, fatigue sets in

---

### **`sessions_to_mastery`**
Number of practice sessions needed

**Example: UNIV_FUNC (Functions)**
```
Total hours: 8.0
Optimal session: 50 minutes (0.83 hours)
Sessions: 8.0 / 0.83 ≈ 10 sessions

But config says: 8 sessions
Why? Because students improve efficiency over time!
```

---

## Planned Use Cases:

### **1. Progress Tracking Dashboard:**
```python
# Show estimated completion time
topic_progress = {
    "current_mastery": 0.45,
    "estimated_hours_remaining": calculate_remaining_hours(),
    "sessions_left": 4,
    "next_session_recommended": "45 minutes"
}
```

### **2. Session Timer:**
```python
# Alert after optimal session length
if session_time > optimal_session_length_minutes:
    notify_user("You've been studying for 50 minutes. Time for a break!")
```

### **3. Motivation Features:**
```python
# Show progress milestones
if problems_completed >= min_practice_problems:
    achievement_unlocked("Problem Master - UNIV_FUNC")
```

---

## Real Example: Learning Functions

**Week 1:**
```
Session 1 (50 min): Problems 1-4 → Mastery: 0.15
Session 2 (50 min): Problems 5-8 → Mastery: 0.28
Session 3 (50 min): Problems 9-15 → Mastery: 0.42
```

**Week 2:**
```
Session 4 (50 min): Problems 16-20 → Mastery: 0.55
Session 5 (50 min): Problems 21-25 → Mastery: 0.66
```

**Week 3:**
```
Session 6 (50 min): Problems 26-28 → Mastery: 0.74
Session 7 (50 min): Problems 29-30 → Mastery: 0.81 ✓ MASTERED!
```

**Actual:** 7 sessions (predicted: 8) → Student exceeded expectations!

---

# STEP 12: Spaced Repetition Intervals - Review Scheduling

## What is it?
Optimal review intervals based on current mastery level, following proven spaced repetition principles (similar to Anki/SuperMemo).

**Status:** ⏳ **NOT IMPLEMENTED** (Phase 2 feature)

## Structure:

```json
{
  "intervals": [
    {
      "mastery_range": [0.0, 0.4],
      "review_after_days": 1,
      "priority": "critical",
      "description": "Very low mastery - review immediately"
    }
  ],
  "decay_acceleration_factors": {
    "no_review_in_7_days": 1.5,
    "no_review_in_14_days": 2.0,
    "no_review_in_30_days": 3.0
  }
}
```

---

## The 6 Review Intervals:

| Mastery Range | Review After | Priority | Status | Color |
|---------------|--------------|----------|--------|-------|
| **0.0 - 0.4** | **1 day** | Critical | 🔴 Forgotten | Red |
| **0.4 - 0.6** | **2 days** | High | 🟡 At risk | Yellow |
| **0.6 - 0.75** | **4 days** | Medium | 🟢 Approaching solid | Green |
| **0.75 - 0.85** | **7 days** | Low | 🟢 Good | Green |
| **0.85 - 0.95** | **14 days** | Very low | 🟣 Strong | Purple |
| **0.95 - 1.0** | **21 days** | Minimal | 🟣 Excellent | Purple |

---

## How It Works:

### **Example: Student's Review Schedule**

**Day 0 - Learn UNIV_VAR:**
```
Mastery: 0.80
Next review: 7 days (weekly)
```

**Day 7 - First Review:**
```
Decayed mastery: 0.72 (decay applied)
Review performance: 85%
New mastery: 0.81
Next review: 7 days (still in 0.75-0.85 range)
```

**Day 14 - Second Review:**
```
Decayed mastery: 0.74
Review performance: 90%
New mastery: 0.87 (jumped to next tier!)
Next review: 14 days (biweekly now!)
```

**Day 28 - Third Review:**
```
Decayed mastery: 0.82
Review performance: 95%
New mastery: 0.96 (mastered!)
Next review: 21 days (monthly maintenance)
```

---

## Decay Acceleration Factors:

**What it is:** Penalties for ignoring review schedules

```json
"decay_acceleration_factors": {
  "no_review_in_7_days": 1.5,
  "no_review_in_14_days": 2.0,
  "no_review_in_30_days": 3.0
}
```

### **Normal Decay:**
```
decay_rate = 0.02 per day
mastery after 10 days = 0.80 × e^(-0.02×10) = 0.655
```

### **Accelerated Decay (ignored for 14 days):**
```
decay_rate = 0.02 × 2.0 = 0.04 per day (doubled!)
mastery after 14 days = 0.80 × e^(-0.04×14) = 0.463
```

**Result:** Knowledge decays TWICE as fast if you ignore review schedules!

---

## Planned Implementation:

```python
# Phase 2: Review reminder system

def calculate_next_review_date(mapping_id, current_mastery, last_practiced):
    # Find matching interval
    for interval in spaced_repetition_intervals['intervals']:
        min_m, max_m = interval['mastery_range']
        if min_m <= current_mastery < max_m:
            days_until_review = interval['review_after_days']
            break
    
    # Calculate next review date
    next_review = last_practiced + timedelta(days=days_until_review)
    
    # Check if overdue
    if datetime.now() > next_review:
        days_overdue = (datetime.now() - next_review).days
        
        # Apply decay acceleration
        if days_overdue > 30:
            decay_multiplier = 3.0
        elif days_overdue > 14:
            decay_multiplier = 2.0
        elif days_overdue > 7:
            decay_multiplier = 1.5
        else:
            decay_multiplier = 1.0
        
        # Apply accelerated decay
        current_mastery *= math.exp(-0.02 * decay_multiplier * days_overdue)
    
    return {
        "next_review_date": next_review,
        "priority": interval['priority'],
        "current_mastery": current_mastery
    }
```

---

## Example Dashboard:

```
📅 Review Schedule:

🔴 CRITICAL - Review Today!
  - UNIV_COND (mastery: 0.32, last practiced: 15 days ago)

🟡 HIGH PRIORITY - Review in 1 day
  - UNIV_VAR (mastery: 0.58, last practiced: 1 day ago)

🟢 UPCOMING - Review in 3 days
  - UNIV_LOOP (mastery: 0.68, last practiced: 1 day ago)

🟢 GOOD - Review in 5 days
  - UNIV_FUNC (mastery: 0.81, last practiced: 2 days ago)

🟣 STRONG - Review in 10 days
  - UNIV_COLL (mastery: 0.92, last practiced: 4 days ago)
```

---

# STEP 13: Milestone Projects - Practical Application Checkpoints

## What is it?
Real-world coding projects that verify mastery across multiple topics.

**Status:** ⏳ **NOT IMPLEMENTED** (Phase 2 feature)

## Structure:

```json
{
  "project_id": "PROJ_TODO_LIST",
  "name": "Todo List Application",
  "required_mappings": ["UNIV_VAR", "UNIV_COND", "UNIV_LOOP", "UNIV_FUNC", "UNIV_COLL"],
  "language_id": "python_3",
  "estimated_completion_minutes": 120,
  "mastery_verification_weight": 1.5,
  "difficulty": 0.6,
  "description": "Create a todo list with add, remove, and list operations"
}
```

---

## All 7 Projects:

| Project | Language | Topics Required | Time | Difficulty | Weight |
|---------|----------|-----------------|------|------------|--------|
| **Basic Calculator** | Python | VAR, COND, FUNC | 60 min | 0.4 ⭐⭐ | 1.3 |
| **Todo List** | Python | VAR, COND, LOOP, FUNC, COLL | 120 min | 0.6 ⭐⭐⭐ | 1.5 |
| **Contact Manager** | Python | VAR, COND, LOOP, FUNC, COLL, OOP | 180 min | 0.75 ⭐⭐⭐⭐ | 1.8 |
| **Interactive Web Page** | JavaScript | VAR, COND, FUNC, COLL | 90 min | 0.55 ⭐⭐⭐ | 1.4 |
| **Student Management** | Java | VAR, COND, LOOP, FUNC, COLL, OOP | 200 min | 0.8 ⭐⭐⭐⭐⭐ | 1.9 |
| **Memory Game** | C++ | VAR, COND, LOOP, FUNC, COLL | 150 min | 0.85 ⭐⭐⭐⭐⭐ | 1.7 |
| **Web Server** | Go | VAR, FUNC, COLL, OOP | 100 min | 0.7 ⭐⭐⭐⭐ | 1.6 |

---

## Field Breakdown:

### **`required_mappings`**
Topics student MUST have practiced before attempting project

**Unlock Logic:**
```python
def can_attempt_project(user_id, project_id):
    project = get_project(project_id)
    
    for mapping_id in project['required_mappings']:
        mastery = get_mastery(user_id, mapping_id)
        
        if mastery < 0.65:  # Below maintenance threshold
            return False, f"Master {mapping_id} first (current: {mastery})"
    
    return True, "Ready to attempt!"
```

---

### **`mastery_verification_weight`**
How much completing this project boosts your mastery

**Example:**
```
Student completes "Todo List" project
Weight: 1.5

For each required topic:
  UNIV_VAR: 0.70 → 0.70 + (0.15 × 1.5) = 0.925
  UNIV_COND: 0.68 → 0.68 + (0.15 × 1.5) = 0.905
  UNIV_LOOP: 0.72 → 0.72 + (0.15 × 1.5) = 0.945
  UNIV_FUNC: 0.75 → 0.75 + (0.15 × 1.5) = 0.975
  UNIV_COLL: 0.71 → 0.71 + (0.15 × 1.5) = 0.935
```

**Result:** Massive boost across all topics!

---

## Example: Todo List Project

**Requirements:**
```python
# Project Spec:
"""
Create a command-line todo list application with:
1. Add new tasks
2. Remove tasks by index
3. List all tasks
4. Mark tasks as complete
5. Filter by status (complete/incomplete)
"""
```

**Topics Verified:**

✓ **UNIV_VAR** - Storing task list, indices, user input  
✓ **UNIV_COND** - If/else for menu choices, status checks  
✓ **UNIV_LOOP** - Iterating tasks, continuous menu loop  
✓ **UNIV_FUNC** - Functions for add/remove/list operations  
✓ **UNIV_COLL** - List data structure for tasks

**Sample Solution:**
```python
tasks = []  # UNIV_COLL

def add_task(task):  # UNIV_FUNC
    tasks.append({"name": task, "done": False})  # UNIV_VAR

def list_tasks():  # UNIV_FUNC
    for i, task in enumerate(tasks):  # UNIV_LOOP
        status = "✓" if task["done"] else "✗"  # UNIV_COND
        print(f"{i}. [{status}] {task['name']}")

while True:  # UNIV_LOOP
    choice = input("1:Add 2:List 3:Quit > ")  # UNIV_VAR
    
    if choice == "1":  # UNIV_COND
        add_task(input("Task: "))
    elif choice == "2":  # UNIV_COND
        list_tasks()
    elif choice == "3":  # UNIV_COND
        break
```

---

# STEP 14: Error Pattern Taxonomy - Common Mistakes Tracking

## What is it?
Categorizes common programming errors by topic and language, with remediation bonuses for fixing past mistakes.

**Status:** ✅ **PARTIALLY IMPLEMENTED** (error tracking exists, remediation bonus implemented)

## Structure:

```json
{
  "error_category": "SYNTAX_ERRORS",
  "mapping_id": "UNIV_SYN_PREC",
  "common_patterns": [
    {
      "error_type": "MISSING_SEMICOLON",
      "applies_to_languages": ["javascript_es6", "java_17", "cpp_20"],
      "severity": 0.3,
      "remediation_boost": 0.08,
      "common_message": "Missing semicolon at end of statement"
    }
  ]
}
```

---

## 7 Error Categories:

### **1. SYNTAX_ERRORS (UNIV_SYN_PREC)**

| Error Type | Languages | Severity | Boost | Description |
|------------|-----------|----------|-------|-------------|
| **MISSING_SEMICOLON** | JS, Java, C++ | 0.3 | 0.08 | Forgot `;` at end of statement |
| **INDENTATION_ERROR** | Python | 0.5 | 0.12 | Wrong indentation level |
| **BRACE_MISMATCH** | JS, Java, C++, Go | 0.4 | 0.10 | Mismatched `{` `}` |

---

### **2. TYPE_ERRORS (UNIV_VAR)**

| Error Type | Languages | Severity | Boost | Description |
|------------|-----------|----------|-------|-------------|
| **TYPE_MISMATCH** | Java, C++, Go | 0.7 | 0.15 | Assigning wrong type to variable |
| **UNDEFINED_VARIABLE** | All | 0.6 | 0.12 | Using variable before declaration |
| **NULL_POINTER_EXCEPTION** | Java, C++ | 0.8 | 0.18 | Accessing null/nullptr reference |

---

### **3. LOGIC_ERRORS (UNIV_COND)**

| Error Type | Languages | Severity | Boost |
|------------|-----------|----------|-------|
| **WRONG_COMPARISON_OPERATOR** | All | 0.5 | 0.10 |
| **BOOLEAN_LOGIC_ERROR** | All | 0.6 | 0.12 |

---

### **4. LOOP_ERRORS (UNIV_LOOP)**

| Error Type | Severity | Boost | Impact |
|------------|----------|-------|--------|
| **INFINITE_LOOP** | 0.9 (HIGH!) | 0.20 | Loop never terminates |
| **OFF_BY_ONE_ERROR** | 0.5 | 0.12 | Loop iterates wrong count |

---

### **5. FUNCTION_ERRORS (UNIV_FUNC)**

| Error Type | Severity | Boost |
|------------|----------|-------|
| **SCOPE_MISUNDERSTANDING** | 0.7 | 0.15 |
| **MISSING_RETURN** | 0.6 | 0.12 |
| **ARGUMENT_MISMATCH** | 0.5 | 0.10 |

---

### **6. COLLECTION_ERRORS (UNIV_COLL)**

| Error Type | Severity | Boost |
|------------|----------|-------|
| **INDEX_OUT_OF_BOUNDS** | 0.7 | 0.14 |
| **KEY_NOT_FOUND** | 0.5 | 0.10 |

---

### **7. OOP_ERRORS (UNIV_OOP)**

| Error Type | Severity | Boost |
|------------|----------|-------|
| **INHERITANCE_MISUSE** | 0.8 | 0.18 |
| **ENCAPSULATION_VIOLATION** | 0.6 | 0.12 |
| **CONSTRUCTOR_ERROR** | 0.7 | 0.15 |

---

## How Remediation Works:

### **Current Implementation:**

```python
# grading_service.py → _calculate_error_remediation_bonus()

def _calculate_error_remediation_bonus(self, user_id, language_id, results):
    # Get previous session errors
    prev_errors_query = text("""
        SELECT ed.questions_snapshot
        FROM exam_details ed
        JOIN exam_sessions es ON ed.session_id = es.id
        WHERE es.user_id = :u AND es.language_id = :l
        ORDER BY es.created_at DESC
        LIMIT 1
    """)
    
    prev_session = self.db.execute(prev_errors_query, {...}).fetchone()
    
    # Build set of error types from previous session
    prev_errors = set()
    for q in prev_snapshot.get('questions', []):
        if not q.get('is_correct') and q.get('error_type'):
            prev_errors.add(q['error_type'])
    
    # Check current session for corrected errors
    total_bonus = 0.0
    for result in results:
        if result.is_correct and result.error_type in prev_errors:
            # User corrected a previous error!
            bonus = self._get_remediation_boost(result.error_type)
            total_bonus += bonus
    
    return min(total_bonus, 0.15)  # Cap at +0.15
```

---

### **Example Scenario:**

**Session 1 (Yesterday):**
```
Question 1: WRONG → error_type: "MISSING_SEMICOLON"
Question 2: WRONG → error_type: "TYPE_MISMATCH"
Question 3: CORRECT
```

**Session 2 (Today):**
```
Question 1: Similar semicolon question → CORRECT ✓
  → System detects: "Fixed MISSING_SEMICOLON error!"
  → Bonus: +0.08

Question 2: Similar type question → CORRECT ✓
  → System detects: "Fixed TYPE_MISMATCH error!"
  → Bonus: +0.15

Total remediation bonus: 0.08 + 0.15 = 0.23 → capped at 0.15
```

**Mastery Update:**
```python
performance = accuracy * difficulty = 0.80 * 0.6 = 0.48
remediation_bonus = 0.15  # Extra credit for learning from mistakes!

new_mastery = (old_mastery * 0.7) + (performance * 0.3) + remediation_bonus
# Significant boost for fixing past errors!
```

---

## Why This Matters:

**Educational Psychology:**
- **Error correction** is a powerful learning mechanism
- **Metacognition** - students learn from their mistakes
- **Positive reinforcement** - reward improvement, not just perfection

**Example Message to Student:**
```
🎉 Great work! You've corrected 2 previous errors:
  ✓ Fixed: MISSING_SEMICOLON (+0.08 bonus)
  ✓ Fixed: TYPE_MISMATCH (+0.15 bonus)

Total remediation bonus: +0.15 mastery!
Keep up the improvement! 📈
```

---

# STEP 15: Prerequisite Strength Weights - Weighted Prerequisites

## What is it?
Defines **weighted importance** of prerequisite topics, where some prerequisites are more critical than others.

**Status:** ⏳ **NOT IMPLEMENTED** (Phase 2 feature - more granular than soft_gates)

## Structure:

```json
{
  "target_mapping_id": "UNIV_OOP",
  "weighted_prerequisites": [
    {
      "prereq_mapping_id": "UNIV_VAR",
      "weight": 0.40,
      "min_mastery_required": 0.70
    },
    {
      "prereq_mapping_id": "UNIV_FUNC",
      "weight": 0.50,
      "min_mastery_required": 0.75
    }
  ],
  "aggregate_threshold": 0.70
}
```

---

## Difference from Soft Gates:

| Feature | Soft Gates | Prerequisite Strength Weights |
|---------|-----------|-------------------------------|
| **Granularity** | Pass/fail check | Weighted scoring |
| **Penalty** | Binary (has violations or not) | Proportional (based on weighted score) |
| **Formula** | Exponential penalty | Weighted average |
| **Flexibility** | All-or-nothing | Partial credit possible |

---

## All 5 Weighted Prerequisite Configurations:

### **1. UNIV_OOP (Hardest Target)**

| Prerequisite | Weight | Min Required | Why? |
|--------------|--------|--------------|------|
| **UNIV_FUNC** | **0.50** (HIGHEST) | 0.75 | Methods ARE functions |
| **UNIV_VAR** | **0.40** | 0.70 | Instance variables critical |
| **UNIV_COLL** | **0.30** | 0.65 | Objects contain collections |

**Aggregate threshold:** 0.70

---

### **2. UNIV_FUNC**

| Prerequisite | Weight | Min Required |
|--------------|--------|--------------|
| **UNIV_VAR** | **0.60** | 0.65 |
| **UNIV_COND** | **0.50** | 0.60 |
| **UNIV_LOOP** | **0.40** | 0.60 |

**Aggregate threshold:** 0.65

---

### **3. UNIV_COLL**

| Prerequisite | Weight | Min Required |
|--------------|--------|--------------|
| **UNIV_VAR** | **0.70** | 0.65 |
| **UNIV_LOOP** | **0.60** | 0.65 |
| **UNIV_FUNC** | **0.40** | 0.60 |

**Aggregate threshold:** 0.68

---

### **4. UNIV_LOOP**

| Prerequisite | Weight | Min Required |
|--------------|--------|--------------|
| **UNIV_COND** | **0.80** | 0.65 |
| **UNIV_VAR** | **0.50** | 0.60 |

**Aggregate threshold:** 0.65

---

### **5. UNIV_COND**

| Prerequisite | Weight | Min Required |
|--------------|--------|--------------|
| **UNIV_VAR** | **0.75** | 0.60 |

**Aggregate threshold:** 0.60

---

## How It Would Work:

```python
# Phase 2 implementation

def calculate_prerequisite_readiness(user_id, language_id, target_mapping_id):
    """
    Calculate weighted prerequisite score.
    More nuanced than binary soft gates.
    """
    config = get_weighted_prereqs(target_mapping_id)
    
    if not config:
        return 1.0  # No prerequisites
    
    total_weight = 0.0
    weighted_score = 0.0
    
    for prereq in config['weighted_prerequisites']:
        prereq_id = prereq['prereq_mapping_id']
        weight = prereq['weight']
        min_required = prereq['min_mastery_required']
        
        # Get actual mastery
        mastery = get_mastery(user_id, language_id, prereq_id)
        
        # Calculate contribution
        if mastery >= min_required:
            # Full credit
            contribution = weight * 1.0
        else:
            # Partial credit (proportional)
            contribution = weight * (mastery / min_required)
        
        weighted_score += contribution
        total_weight += weight
    
    # Normalize to 0-1 range
    readiness = weighted_score / total_weight
    
    return readiness
```

---

## Example Calculation: OOP Readiness

**Student wants to learn UNIV_OOP:**

**Current Mastery:**
```
UNIV_VAR:  0.65
UNIV_FUNC: 0.80
UNIV_COLL: 0.55
```

**Weighted Calculation:**
```python
# UNIV_VAR contribution
weight = 0.40
min_required = 0.70
mastery = 0.65
contribution = 0.40 * (0.65 / 0.70) = 0.371

# UNIV_FUNC contribution
weight = 0.50
min_required = 0.75
mastery = 0.80  # Above minimum!
contribution = 0.50 * 1.0 = 0.500

# UNIV_COLL contribution
weight = 0.30
min_required = 0.65
mastery = 0.55
contribution = 0.30 * (0.55 / 0.65) = 0.254

# Total
total_weight = 0.40 + 0.50 + 0.30 = 1.20
weighted_score = 0.371 + 0.500 + 0.254 = 1.125
readiness = 1.125 / 1.20 = 0.9375

# Check aggregate threshold
aggregate_threshold = 0.70
readiness (0.94) >= threshold (0.70) ✓ READY!
```

**Result:** Student can attempt OOP, but with recommendations:
```
✓ Ready to start UNIV_OOP!

Prerequisite Status:
  ✓ UNIV_FUNC: 0.80 / 0.75 (strong!)
  ⚠️ UNIV_VAR: 0.65 / 0.70 (slightly weak)
  ⚠️ UNIV_COLL: 0.55 / 0.65 (needs review)

Recommendation: Review UNIV_COLL before diving deep into OOP.
```

---

# STEP 16: Concept Interdependencies - Bidirectional Concept Reinforcement

## What is it?
Describes how concepts **reinforce** each other bidirectionally and what minimum understanding is required.

**Status:** ✅ **FULLY IMPLEMENTED** (as `concept_interdependencies_config.json`)

## Structure:

```json
{
  "mapping_id": "UNIV_LOOP",
  "reinforces": [
    {
      "target_mapping_id": "UNIV_COND",
      "strength": 0.80,
      "description": "Loop conditions reinforce boolean logic"
    }
  ],
  "requires_understanding_of": [
    {
      "source_mapping_id": "UNIV_COND",
      "minimum_mastery": 0.60,
      "description": "Must understand conditionals for loop termination"
    }
  ]
}
```

---

## All 4 Interdependency Configurations:

### **1. UNIV_LOOP**

**Reinforces:**
- `UNIV_COND` (strength: 0.80) - Loop conditions reinforce boolean logic
- `UNIV_VAR` (strength: 0.50) - Loop counters reinforce variable manipulation

**Requires:**
- `UNIV_COND` (min: 0.60) - Must understand conditionals for loop termination

---

### **2. UNIV_FUNC**

**Reinforces:**
- `UNIV_VAR` (strength: 0.70) - Function parameters deepen variable understanding
- `UNIV_LOOP` (strength: 0.60) - Functions often contain loops
- `UNIV_COND` (strength: 0.65) - Functions often contain conditional logic

**Requires:**
- `UNIV_VAR` (min: 0.65) - Must understand variables for parameters and returns

---

### **3. UNIV_COLL**

**Reinforces:**
- `UNIV_LOOP` (strength: 0.85, HIGHEST!) - Iterating collections heavily reinforces loops
- `UNIV_VAR` (strength: 0.60) - Collection elements reinforce type understanding

**Requires:**
- `UNIV_VAR` (min: 0.65) - Must understand types for collection usage
- `UNIV_LOOP` (min: 0.65) - Must understand loops to iterate collections

---

### **4. UNIV_OOP**

**Reinforces:**
- `UNIV_FUNC` (strength: 0.75) - Methods deepen function understanding
- `UNIV_COLL` (strength: 0.55) - Object state management reinforces collections
- `UNIV_VAR` (strength: 0.60) - Instance variables reinforce type understanding

**Requires:**
- `UNIV_FUNC` (min: 0.70) - Must understand functions for methods
- `UNIV_VAR` (min: 0.70) - Must understand variables for instance state

---

## How It's Implemented:

```python
# grading_service.py → _apply_concept_interdependencies()

def _apply_concept_interdependencies(self, user_id, language_id, mapping_id, new_mastery):
    """
    Apply bidirectional reinforcement between related concepts.
    """
    interdeps = self.config.transition_map.get('concept_interdependencies', [])
    applied = []
    
    for interdep in interdeps:
        mapping_a = interdep.get('mapping_a')
        mapping_b = interdep.get('mapping_b')
        coefficient = interdep.get('reinforcement_coefficient', 0.0)
        
        # Check if current mapping matches either side
        if mapping_id == mapping_a:
            target_mapping = mapping_b
        elif mapping_id == mapping_b:
            target_mapping = mapping_a
        else:
            continue
        
        # Calculate boost
        boost_amount = new_mastery * coefficient
        
        # Apply to database
        update = text("""
            UPDATE student_state
            SET mastery_score = LEAST(mastery_score + :boost, 1.0)
            WHERE user_id = :u AND language_id = :l AND mapping_id = :m
        """)
        
        result = self.db.execute(update, {"boost": boost_amount, ...})
        
        if result.rowcount > 0:
            applied.append(f"{target_mapping}:+{boost_amount:.3f}")
    
    return applied
```

---

## Example: Learning Collections

**Student completes UNIV_COLL exam:**
```
New mastery: 0.75
```

**Reinforcement Applied:**

1. **UNIV_LOOP boost:**
   ```
   strength = 0.85
   boost = 0.75 * 0.85 = 0.6375
   
   But wait! This is too high!
   Actual implementation uses reinforcement_coefficient from concept_interdependencies_config.json:
   boost = 0.75 * 0.10 = 0.075
   
   UNIV_LOOP: 0.68 → 0.755
   ```

2. **UNIV_VAR boost:**
   ```
   boost = 0.75 * 0.07 = 0.0525
   UNIV_VAR: 0.70 → 0.7525
   ```

**Result:**
```
Completing UNIV_COLL reinforced:
  - UNIV_LOOP: +0.075
  - UNIV_VAR: +0.053
```

---

## Summary Table: All Sections Implementation Status

| # | Section | Purpose | Status | Where Used |
|---|---------|---------|--------|------------|
| **1** | Config | Global decay/thresholds | ✅ Implemented | `state_vector_service.py`, all services |
| **2** | Experience Levels | User registration priming | ✅ Implemented | `user_service.py` |
| **3** | Universal Transitions | Sequential topic transfer | ⏳ Phase 2 | Not yet (difficulty adaptation) |
| **4** | Intra-Language Synergy | Same-language reinforcement | ✅ Implemented | `grading_service.py → _apply_synergy()` |
| **5** | Cross-Language Transfer | Multi-language knowledge transfer | ✅ Implemented | `grading_service.py → _apply_cross_language_transfer()` |
| **6** | Mapping-Specific Transfer | Fine-grained transfer rates | ✅ Implemented | `grading_service.py` (checks specific first) |
| **7** | Soft Gates | Prerequisite enforcement | ✅ Implemented | `grading_service.py → _check_soft_gates()` |
| **8** | Language-Specific Modifiers | Per-language difficulty | ⏳ Phase 2 | Not yet (question selection) |
| **9** | Question Difficulty Tiers | Progressive challenge system | ✅ Partial | `config.py → get_difficulty_tier()` |
| **10** | Adaptive Difficulty Curves | Dynamic difficulty adjustment | ⏳ Phase 2 | Not yet (adaptive system) |
| **11** | Temporal Learning Patterns | Time-based estimates | ⏳ Phase 2 | Not yet (analytics/progress tracking) |
| **12** | Spaced Repetition Intervals | Review scheduling | ⏳ Phase 2 | Not yet (review reminders) |
| **13** | Milestone Projects | Practical verification | ⏳ Phase 2 | Not yet (project system) |
| **14** | Error Pattern Taxonomy | Common mistakes tracking | ✅ Partial | `grading_service.py → _calculate_error_remediation_bonus()` |
| **15** | Prerequisite Strength Weights | Weighted prerequisites | ⏳ Phase 2 | Not yet (more granular than soft_gates) |
| **16** | Concept Interdependencies | Bidirectional reinforcement | ✅ Implemented | `grading_service.py → _apply_concept_interdependencies()` |

---

**End of Document**

This comprehensive guide covers ALL sections of transition_map.json with implementation status, real-world examples, and code snippets showing how each feature works (or will work in Phase 2).
