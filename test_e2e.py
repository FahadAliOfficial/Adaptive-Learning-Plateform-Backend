import requests
import random

api = "http://localhost:8000"

print("\n=== COMPREHENSIVE E2E TEST ===\n")

# 1. REGISTER
print("1. USER REGISTRATION")
test_email = f"e2e_test_{random.randint(10000, 99999)}@test.com"
test_password = "TestPass123!"

reg_response = requests.post(f"{api}/api/user/register", json={
    "email": test_email,
    "password": test_password,
    "name": "E2E Test",
    "language_id": "python_3"
})
if reg_response.status_code == 200:
    user_data = reg_response.json()
    user_id = user_data["user_id"]
    print(f"✓ User registered: {test_email} ({user_id})")
else:
    print(f"✗ Registration failed: {reg_response.text}")
    exit(1)

# 2. LOGIN
print("\n2. LOGIN")
login_response = requests.post(f"{api}/api/auth/login", json={
    "email": test_email,
    "password": test_password
})
if login_response.status_code == 200:
    token_data = login_response.json()
    token = token_data["access_token"]
    print(f"✓ Login successful, token: {token[:20]}...")
    headers = {"Authorization": f"Bearer {token}"}
else:
    print(f"✗ Login failed: {login_response.text}")
    exit(1)

# 3. RL RECOMMENDATION
print("\n3. RL RECOMMENDATION")
rec_response = requests.post(f"{api}/api/rl/recommend", headers=headers, json={
    "user_id": user_id,
    "language_id": "python_3",
    "strategy": "a2c"
})
if rec_response.status_code == 200:
    rec_data = rec_response.json()
    print(f"✓ Recommendation: {rec_data['major_topic_id']} at difficulty {rec_data['difficulty']}")
    recommended_topic = rec_data['major_topic_id']
else:
    print(f"✗ Recommendation failed: {rec_response.text}")
    exit(1)

# 3.5. START EXAM SESSION
print("\n3.5. START EXAM SESSION")
start_response = requests.post(f"{api}/api/exam/start", headers=headers, json={
    "user_id": user_id,
    "language_id": "python_3",
    "major_topic_id": recommended_topic,
    "session_type": "practice"
})
if start_response.status_code == 200:
    session_data = start_response.json()
    session_id = session_data["session_id"]
    print(f"✓ Session started: {session_id}")
else:
    print(f"✗ Session start failed: {start_response.text}")
    exit(1)

# 4. EXAM SUBMISSION
print("\n4. EXAM SUBMISSION")
exam_response = requests.post(f"{api}/api/exam/submit", headers=headers, json={
    "user_id": user_id,
    "session_id": session_id,
    "language_id": "python_3",
    "major_topic_id": recommended_topic,
    "session_type": "practice",
    "results": [
        {
            "q_id": "test_q_1",
            "sub_topic": "conditionals",
            "difficulty": 0.2,
            "is_correct": True,
            "selected_choice": "A",
            "correct_choice": "A",
            "time_spent": 30.0,
            "expected_time": 25.0,
            "error_type": None
        },
        {
            "q_id": "test_q_2",
            "sub_topic": "conditionals",
            "difficulty": 0.2,
            "is_correct": True,
            "selected_choice": "B",
            "correct_choice": "B",
            "time_spent": 35.0,
            "expected_time": 25.0,
            "error_type": None
        },
        {
            "q_id": "test_q_3",
            "sub_topic": "conditionals",
            "difficulty": 0.2,
            "is_correct": True,
            "selected_choice": "C",
            "correct_choice": "C",
            "time_spent": 40.0,
            "expected_time": 25.0,
            "error_type": None
        },
        {
            "q_id": "test_q_4",
            "sub_topic": "conditionals",
            "difficulty": 0.2,
            "is_correct": True,
            "selected_choice": "D",
            "correct_choice": "D",
            "time_spent": 20.0,
            "expected_time": 25.0,
            "error_type": None
        },
        {
            "q_id": "test_q_5",
            "sub_topic": "conditionals",
            "difficulty": 0.2,
            "is_correct": True,
            "selected_choice": "A",
            "correct_choice": "A",
            "time_spent": 25.0,
            "expected_time": 25.0,
            "error_type": None
        }
    ],
    "total_time_seconds": 300
})
if exam_response.status_code == 200:
    exam_data = exam_response.json()
    print(f"✓ Exam submitted successfully")
    print(f"  New mastery: {exam_data.get('new_mastery_score', 'N/A')}")
    print(f"  Accuracy: {exam_data.get('accuracy', 'N/A')}")
else:
    print(f"✗ Exam submission failed: {exam_response.text}")

# 5. CHECK RECOMMENDATION HISTORY
print("\n5. CHECK RECOMMENDATION HISTORY")
history_response = requests.get(f"{api}/api/rl/history/{user_id}", headers=headers)
if history_response.status_code == 200:
    history_data = history_response.json()
    followed_up = history_data['history'][0]['followed_up']
    print(f"✓ History: {history_data['total_recommendations']} recs, Followed: {followed_up}")
    if followed_up:
        print("  SUCCESS: Recommendation marked as followed!")
    else:
        print("  WARNING: Recommendation NOT marked as followed")
else:
    print(f"✗ History check failed: {history_response.text}")

# 6. STATE VECTOR GENERATION
print("\n6. STATE VECTOR GENERATION")
state_response = requests.post(f"{api}/api/rl/state-vector", headers=headers, json={
    "user_id": user_id,
    "language_id": "python_3"
})
if state_response.status_code == 200:
    state_data = state_response.json()
    print(f"✓ State vector: {len(state_data['state_vector'])} dimensions")
else:
    print(f"✗ State vector failed: {state_response.text}")

# 7. RL SERVICE HEALTH
print("\n7. RL SERVICE HEALTH")
health_response = requests.get(f"{api}/api/rl/health", headers=headers)
if health_response.status_code == 200:
    health_data = health_response.json()
    print(f"✓ Service health: {health_data['status']}, Models: {len(health_data['models_loaded'])}/3")
else:
    print(f"✗ Health check failed: {health_response.text}")

# 8. USER OWNERSHIP TEST (Security)
print("\n8. USER OWNERSHIP TEST (Security)")
bad_response = requests.post(f"{api}/api/rl/recommend", headers=headers, json={
    "user_id": "00000000-0000-0000-0000-000000000001",
    "language_id": "python_3",
    "strategy": "a2c"
})
if bad_response.status_code == 403:
    print("✓ Correctly blocked access to other user's data (403)")
elif bad_response.status_code == 200:
    print("✗ SECURITY BREACH: Got recommendation for other user!")
else:
    print(f"✗ Unexpected error: {bad_response.status_code} - {bad_response.text}")

print("\n=== ALL TESTS COMPLETE ===\n")
