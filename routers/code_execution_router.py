"""
Code Execution Router
API endpoints for Judge0 code execution and validation.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
import logging

from services.judge0_service import get_judge0_service
from services.code_wrapper import wrap_code
from services.auth import get_current_admin_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/code-execution", tags=["Code Execution"])


# Request/Response Models
class CodeExecutionRequest(BaseModel):
    """Request model for code execution."""
    language_id: str = Field(..., description="Language ID (e.g., 'python_3')")
    source_code: str = Field(..., description="Source code to execute")
    stdin: Optional[str] = Field("", description="Standard input")
    wrap_code: bool = Field(True, description="Auto-wrap code in boilerplate")


class CodeExecutionResponse(BaseModel):
    """Response model for code execution."""
    status: str = Field(..., description="Execution status (e.g., 'Accepted')")
    status_id: int = Field(..., description="Numeric status ID")
    stdout: str = Field("", description="Standard output")
    stderr: str = Field("", description="Standard error")
    compile_output: str = Field("", description="Compilation output")
    message: str = Field("", description="Error message")
    time: Optional[float] = Field(None, description="Execution time in seconds")
    memory: Optional[int] = Field(None, description="Memory usage in KB")
    exit_code: Optional[int] = Field(None, description="Process exit code")
    token: str = Field("", description="Judge0 submission token")


class QuestionValidationRequest(BaseModel):
    """Request model for question validation."""
    question_id: str = Field(..., description="Question ID")
    code_snippet: str = Field(..., description="Code snippet from question")
    correct_answer: str = Field(..., description="Text of correct answer option")
    language_id: str = Field(..., description="Language ID")
    wrap_code: bool = Field(True, description="Auto-wrap code in boilerplate")


class QuestionValidationResponse(BaseModel):
    """Response model for question validation."""
    is_valid: bool = Field(..., description="Whether execution succeeded")
    matched: bool = Field(..., description="Whether output matches correct answer")
    execution_result: Dict[str, Any] = Field(..., description="Full execution result")
    comparison: Dict[str, Any] = Field(..., description="Comparison details")


@router.post("/run", response_model=CodeExecutionResponse)
async def run_code(
    request: CodeExecutionRequest,
    current_admin: dict = Depends(get_current_admin_user)
):
    """
    Execute code using Judge0.
    
    **Requires:** Valid JWT access token (admin only)
    
    Args:
        request: Code execution request
        
    Returns:
        Execution result with stdout, stderr, status, etc.
    """
    try:
        judge0 = get_judge0_service()
        
        # Auto-wrap code if requested
        source_code = request.source_code
        if request.wrap_code:
            try:
                source_code = wrap_code(request.language_id, request.source_code)
                logger.info(f"Auto-wrapped code for {request.language_id}")
            except Exception as e:
                logger.warning(f"Code wrapping failed: {e}, using original code")
        
        # Execute code
        result = judge0.execute_code(
            request.language_id,
            source_code,
            request.stdin
        )
        
        logger.info(
            f"Code execution: admin={current_admin['id']}, "
            f"lang={request.language_id}, status={result['status']}"
        )
        
        return CodeExecutionResponse(**result)
    
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Code execution failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Execution failed: {str(e)}"
        )


@router.post("/validate-question", response_model=QuestionValidationResponse)
async def validate_question(
    request: QuestionValidationRequest,
    current_admin: dict = Depends(get_current_admin_user)
):
    """
    Execute code and validate against correct answer.
    
    **Requires:** Valid JWT access token (admin only)
    
    Args:
        request: Question validation request
        
    Returns:
        Validation result with match status and comparison
    """
    try:
        judge0 = get_judge0_service()
        
        # Auto-wrap code if requested
        source_code = request.code_snippet
        if request.wrap_code:
            try:
                source_code = wrap_code(
                    request.language_id,
                    request.code_snippet,
                    request.correct_answer
                )
                logger.info(f"Auto-wrapped code for validation: {request.language_id}")
            except Exception as e:
                logger.warning(f"Code wrapping failed: {e}, using original code")
        
        # Execute code
        result = judge0.execute_code(request.language_id, source_code)
        
        # Determine if execution was successful
        is_valid = result["status_id"] == 3  # 3 = Accepted
        
        # Compare output with correct answer (trimmed, case-sensitive)
        actual_output = result["stdout"].strip()
        expected_output = request.correct_answer.strip()
        matched = actual_output == expected_output
        
        # Log validation attempt
        logger.info(
            f"Question validation: admin={current_admin['id']}, "
            f"question={request.question_id}, lang={request.language_id}, "
            f"valid={is_valid}, matched={matched}"
        )
        
        return QuestionValidationResponse(
            is_valid=is_valid,
            matched=matched,
            execution_result=result,
            comparison={
                "expected": expected_output,
                "actual": actual_output,
                "match": matched,
                "expected_length": len(expected_output),
                "actual_length": len(actual_output)
            }
        )
    
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Question validation failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Validation failed: {str(e)}"
        )


@router.get("/health")
async def check_judge0_health(
    current_admin: dict = Depends(get_current_admin_user)
):
    """
    Check Judge0 service health.
    
    **Requires:** Valid JWT access token
    
    Returns:
        Health status and available languages count
    """
    try:
        judge0 = get_judge0_service()
        health = judge0.check_health()
        return health
    except Exception as e:
        logger.error(f"Judge0 health check failed: {e}")
        return {
            "healthy": False,
            "error": str(e)
        }
