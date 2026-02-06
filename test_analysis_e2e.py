"""
Test exam analysis end-to-end (requires server running)
Usage:
1. Start the server: uvicorn main:app --reload
2. Run this test: python test_analysis_e2e.py
"""
import requests
import time
import uuid

API = "http://localhost:8000"

def test_exam_analysis():
    print("🧪 Testing OpenAI Exam Analysis End-to-End")
    print("="*60)
    
    # Step 1: Create test user
    print("\n[1] Creating test user...")
    email = f"openai_test_{uuid.uuid4().hex[:8]}@test.com"
    
    reg = requests.post(f"{API}/api/user/register", json={
        "email": email,
        "password": "password123",
        "language_id": "python_3",
        "experience_level": "beginner"
    })
    
    if reg.status_code != 200:
        print(f"   ❌ Registration failed: {reg.status_code}")
        print(f"   Response: {reg.text}")
        return
    
    # Get user_id from response (server generates it, ignores request user_id)
    user_id = reg.json()["user_id"]
    print(f"   ✅ User created: {user_id[:8]}...")
    
    # Step 2: Login
    print("\n[2] Logging in...")
    login = requests.post(f"{API}/api/auth/login", json={
        "email": email,
        "password": "password123"
    })
    
    if login.status_code != 200:
        print(f"   ❌ Login failed: {login.status_code}")
        return
    
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    print(f"   ✅ Logged in")
    
    # Step 3: Start exam session
    print("\n[3] Starting exam session...")
    start = requests.post(f"{API}/api/exam/start", json={
        "user_id": user_id,
        "language_id": "python_3",
        "major_topic_id": "PY_COND_01",
        "session_type": "practice"
    }, headers=headers)
    
    if start.status_code != 200:
        print(f"   ❌ Session start failed: {start.status_code}")
        return
    
    session_id = start.json()["session_id"]
    print(f"   ✅ Session started: {session_id[:8]}...")
    
    # Step 4: Submit exam with errors (to test meaningful analysis)
    print("\n[4] Submitting exam with mixed results...")
    submit = requests.post(f"{API}/api/exam/submit", json={
        "session_id": session_id,
        "user_id": user_id,
        "language_id": "python_3",
        "major_topic_id": "PY_COND_01",
        "session_type": "practice",
        "total_time_seconds": 240,
        "results": [
            {
                "q_id": "q1",
                "sub_topic": "If Statements",
                "difficulty": 0.3,
                "is_correct": True,
                "selected_choice": "A",
                "correct_choice": "A",
                "time_spent": 40,
                "expected_time": 60,
                "error_type": None
            },
            {
                "q_id": "q2",
                "sub_topic": "Comparison Operators",
                "difficulty": 0.5,
                "is_correct": False,
                "selected_choice": "B",
                "correct_choice": "C",
                "time_spent": 80,
                "expected_time": 60,
                "error_type": "WRONG_COMPARISON_OPERATOR"
            },
            {
                "q_id": "q3",
                "sub_topic": "Nested Conditions",
                "difficulty": 0.7,
                "is_correct": False,
                "selected_choice": "D",
                "correct_choice": "A",
                "time_spent": 120,
                "expected_time": 90,
                "error_type": "LOGIC_ERROR"
            },
            {
                "q_id": "q4",
                "sub_topic": "Elif Chains",
                "difficulty": 0.4,
                "is_correct": True,
                "selected_choice": "C",
                "correct_choice": "C",
                "time_spent": 50,
                "expected_time": 60,
                "error_type": None
            },
            {
                "q_id": "q5",
                "sub_topic": "Boolean Logic",
                "difficulty": 0.6,
                "is_correct": False,
                "selected_choice": "A",
                "correct_choice": "B",
                "time_spent": 90,
                "expected_time": 70,
                "error_type": "LOGIC_ERROR"
            }
        ]
    }, headers=headers)
    
    if submit.status_code != 200:
        print(f"   ❌ Submission failed: {submit.status_code}")
        print(f"   Response: {submit.text}")
        return
    
    result = submit.json()
    print(f"   ✅ Exam submitted")
    print(f"   📊 Results: 2/5 correct (40% accuracy)")
    print(f"   Accuracy: {result['accuracy']*100:.0f}%")
    print(f"   Fluency: {result['fluency_ratio']*100:.0f}%")
    print(f"   New Mastery: {result['new_mastery_score']:.2f}")
    
    # Step 5: Poll for analysis (background task should complete in ~2-5s)
    print("\n[5] Waiting for analysis generation (OpenAI GPT-4o-mini)...")
    print("    Checking every 2 seconds...")
    
    for attempt in range(15):  # 30 seconds max
        time.sleep(2)
        
        analysis = requests.get(f"{API}/api/exam/analysis/{session_id}", headers=headers)
        
        if analysis.status_code != 200:
            print(f"   ❌ Analysis check failed: {analysis.status_code}")
            continue
        
        data = analysis.json()
        status = data["status"]
        
        print(f"   [{attempt+1}] Status: {status}")
        
        if status == "completed":
            print(f"\n✅ ANALYSIS COMPLETED!")
            print(f"\n📊 Personalized Feedback (GPT-4o-mini):")
            bullets = data["bullets"]
            if bullets:
                for i, bullet in enumerate(bullets, 1):
                    print(f"   {i}. {bullet}")
                print(f"\n   Generated at: {data['generated_at']}")
                print(f"\n🎉 SUCCESS! OpenAI integration working end-to-end")
                return True
            else:
                print("   ⚠️ No bullets returned")
                return False
        
        elif status == "failed":
            print(f"\n❌ Analysis generation failed!")
            print(f"   Error: {data.get('error', 'Unknown')}")
            return False
        
        elif status in ["pending", "generating"]:
            continue
    
    print(f"\n⚠️ Analysis not completed after 30 seconds")
    print(f"   This might indicate:")
    print(f"   - Background task not started")
    print(f"   - OpenAI API call taking too long")
    print(f"   - API key issue")
    print(f"\n   Check server logs for details")
    return False

if __name__ == "__main__":
    print("\n⚠️  Make sure the server is running:")
    print("   uvicorn main:app --reload\n")
    
    input("Press Enter when server is ready... ")
    
    try:
        test_exam_analysis()
    except requests.exceptions.ConnectionError:
        print("\n❌ Cannot connect to server!")
        print("   Start the server with: uvicorn main:app --reload")
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
