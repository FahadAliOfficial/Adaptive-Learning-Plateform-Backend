import requests

try:
    resp = requests.get("http://localhost:8000/api/health", timeout=3)
    print(f"Server status: {resp.status_code}")
    print(f"Response: {resp.json()}")
except requests.Timeout:
    print("Server timeout - is it running?")
except requests.ConnectionError:
    print("Cannot connect - is server running?")
except Exception as e:
    print(f"Error: {e}")
