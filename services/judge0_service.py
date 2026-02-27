"""
Judge0 Code Execution Service
Handles communication with Judge0 API for code compilation and execution.
"""

import requests
import time
import os
from typing import Dict, Optional, Any
from dotenv import load_dotenv

load_dotenv()


class Judge0Service:
    """Service for interacting with Judge0 code execution API."""
    
    # Language ID mapping: app language_id -> Judge0 language_id
    # Note: IDs kept for compatibility, versions reflect custom Docker container
    LANGUAGE_MAP = {
        "python_3": 71,      # Python 3.11.0 (custom Docker upgrade from 3.8.1)
        "javascript_es6": 63, # Node.js 20.11.0 (custom Docker upgrade from 12.14.0)
        "java_17": 62,       # Java 13.0.1 (ID name kept for compatibility, actual version matches Judge0 base)
        "cpp_20": 76,        # GCC 8.3.0 C++17 max (ID name kept for compatibility, C++20 not supported without GCC 10+)
        "go_1_21": 60,       # Go 1.21.0 (custom Docker upgrade from 1.13.5)
    }
    
    def __init__(self, base_url: Optional[str] = None, timeout: int = 10):
        """
        Initialize Judge0 service.
        
        Args:
            base_url: Judge0 API base URL (defaults to JUDGE0_URL env var or localhost:2358)
            timeout: Request timeout in seconds
        """
        self.base_url = base_url or os.getenv("JUDGE0_URL", "http://localhost:2358")
        self.timeout = timeout
        
    def get_judge0_language_id(self, language_id: str) -> int:
        """
        Convert app language ID to Judge0 language ID.
        
        Args:
            language_id: App language ID (e.g., "python_3")
            
        Returns:
            Judge0 language ID
            
        Raises:
            ValueError: If language not supported
        """
        judge0_id = self.LANGUAGE_MAP.get(language_id)
        if judge0_id is None:
            raise ValueError(f"Unsupported language: {language_id}")
        return judge0_id
    
    def submit_code(
        self, 
        language_id: str, 
        source_code: str, 
        stdin: str = ""
    ) -> str:
        """
        Submit code to Judge0 for execution.
        
        Args:
            language_id: App language ID (e.g., "python_3")
            source_code: Source code to execute
            stdin: Standard input for the program
            
        Returns:
            Submission token for retrieving results
            
        Raises:
            requests.RequestException: If submission fails
            ValueError: If language not supported
        """
        judge0_lang_id = self.get_judge0_language_id(language_id)
        
        payload = {
            "language_id": judge0_lang_id,
            "source_code": source_code,
            "stdin": stdin,
        }
        
        response = requests.post(
            f"{self.base_url}/submissions?wait=false",
            json=payload,
            timeout=self.timeout
        )
        
        if not response.ok:
            error_detail = response.text
            try:
                error_json = response.json()
                error_detail = error_json
            except:
                pass
            raise requests.RequestException(
                f"Judge0 submission failed (status {response.status_code}): {error_detail}"
            )
        
        return response.json()["token"]
    
    def get_submission_result(
        self, 
        token: str, 
        max_retries: int = 15, 
        delay: float = 1.5
    ) -> Dict[str, Any]:
        """
        Poll Judge0 for submission results.
        
        Args:
            token: Submission token
            max_retries: Maximum polling attempts
            delay: Delay between retries in seconds
            
        Returns:
            Submission result dictionary
            
        Raises:
            requests.RequestException: If request fails
            TimeoutError: If result not ready after max_retries
        """
        for attempt in range(max_retries):
            response = requests.get(
                f"{self.base_url}/submissions/{token}",
                timeout=self.timeout
            )
            response.raise_for_status()
            
            data = response.json()
            status_id = data.get("status", {}).get("id", 0)
            
            # Status IDs: 1=In Queue, 2=Processing, >2=done
            if status_id > 2:
                return data
            
            if attempt < max_retries - 1:
                time.sleep(delay)
        
        # Return last result even if not completed
        return data
    
    def execute_code(
        self, 
        language_id: str, 
        source_code: str,
        stdin: str = ""
    ) -> Dict[str, Any]:
        """
        Submit code and wait for results (convenience method).
        
        Args:
            language_id: App language ID (e.g., "python_3")
            source_code: Source code to execute
            stdin: Standard input for the program
            
        Returns:
            Execution result with keys:
                - status: Status description (e.g., "Accepted", "Compilation Error")
                - status_id: Numeric status ID
                - stdout: Standard output (trimmed)
                - stderr: Standard error (trimmed)
                - compile_output: Compilation output (trimmed)
                - message: Error message if any
                - time: Execution time in seconds
                - memory: Memory usage in KB
                - exit_code: Process exit code
                
        Raises:
            requests.RequestException: If Judge0 request fails
            ValueError: If language not supported
        """
        token = self.submit_code(language_id, source_code, stdin)
        result = self.get_submission_result(token)
        
        # Extract and clean result fields
        return {
            "status": result.get("status", {}).get("description", "Unknown"),
            "status_id": result.get("status", {}).get("id", 0),
            "stdout": (result.get("stdout") or "").strip(),
            "stderr": (result.get("stderr") or "").strip(),
            "compile_output": (result.get("compile_output") or "").strip(),
            "message": (result.get("message") or "").strip(),
            "time": result.get("time"),
            "memory": result.get("memory"),
            "exit_code": result.get("exit_code"),
            "token": token
        }
    
    def check_health(self) -> Dict[str, Any]:
        """
        Check if Judge0 service is available.
        
        Returns:
            Dictionary with health status and available languages
            
        Raises:
            requests.RequestException: If Judge0 is unreachable
        """
        try:
            response = requests.get(
                f"{self.base_url}/languages",
                timeout=self.timeout
            )
            response.raise_for_status()
            languages = response.json()
            
            return {
                "healthy": True,
                "available_languages": len(languages),
                "base_url": self.base_url
            }
        except requests.RequestException as e:
            return {
                "healthy": False,
                "error": str(e),
                "base_url": self.base_url
            }


# Singleton instance
_judge0_service = None


def get_judge0_service() -> Judge0Service:
    """Get or create Judge0 service singleton."""
    global _judge0_service
    if _judge0_service is None:
        _judge0_service = Judge0Service()
    return _judge0_service
