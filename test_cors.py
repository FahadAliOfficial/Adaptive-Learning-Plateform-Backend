"""
Quick test to verify CORS configuration
Run this from a different origin to test CORS headers
"""
import requests

BASE_URL = "http://localhost:8000"

def test_cors():
    print("🔍 Testing CORS Configuration...")
    print("="*60)
    
    # Test 1: Health endpoint (no auth required)
    print("\n1️⃣  Testing /api/health (public endpoint)...")
    try:
        response = requests.get(
            f"{BASE_URL}/api/health",
            headers={"Origin": "http://localhost:3000"}
        )
        
        cors_header = response.headers.get("access-control-allow-origin")
        print(f"   Status: {response.status_code}")
        print(f"   CORS Header: {cors_header}")
        
        if cors_header:
            print("   ✅ CORS is configured!")
        else:
            print("   ❌ CORS header not found")
            
    except Exception as e:
        print(f"   ❌ Error: {e}")
    
    # Test 2: OPTIONS preflight request
    print("\n2️⃣  Testing OPTIONS preflight request...")
    try:
        response = requests.options(
            f"{BASE_URL}/api/auth/login",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type"
            }
        )
        
        print(f"   Status: {response.status_code}")
        print(f"   Allow-Origin: {response.headers.get('access-control-allow-origin')}")
        print(f"   Allow-Methods: {response.headers.get('access-control-allow-methods')}")
        print(f"   Allow-Headers: {response.headers.get('access-control-allow-headers')}")
        
        if response.status_code == 200:
            print("   ✅ Preflight working!")
        else:
            print("   ⚠️  Preflight returned non-200")
            
    except Exception as e:
        print(f"   ❌ Error: {e}")
    
    # Test 3: Verify API docs are accessible
    print("\n3️⃣  Testing API Documentation...")
    try:
        response = requests.get(f"{BASE_URL}/api/docs")
        if response.status_code == 200:
            print(f"   ✅ Swagger UI available at {BASE_URL}/api/docs")
        else:
            print(f"   ⚠️  Swagger UI returned {response.status_code}")
    except Exception as e:
        print(f"   ❌ Error: {e}")
    
    print("\n" + "="*60)
    print("🎯 CORS Test Complete!")
    print(f"\n📚 API Documentation: {BASE_URL}/api/docs")
    print(f"📖 ReDoc: {BASE_URL}/api/redoc")

if __name__ == "__main__":
    print("\n⚠️  Make sure the backend server is running first!")
    print("   Run: uvicorn main:app --reload\n")
    
    input("Press Enter to start tests...")
    test_cors()
