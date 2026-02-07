"""
Multi-language code validator with syntax checking.
Supports Python, JavaScript, Java, C++, Go.

Loophole Fix #2: Validates ALL 5 languages, not just Python
Loophole Fix #10: Rejects "None of the above" and lazy options

Design Philosophy:
- Python: Use ast module (no dependencies)
- Other languages: Use compiler checks (subprocess)
- Graceful degradation: If compiler missing, use regex fallback
"""
import ast
import subprocess
import tempfile
import os
import re
import hashlib
from typing import Tuple, Dict


class MultiLanguageValidator:
    """
    Validates code syntax for all supported languages.
    Returns (is_valid: bool, error_message: str)
    """
    
    # Regex patterns for basic syntax checking (fallback only)
    BASIC_PATTERNS = {
        "javascript_es6": r"^(?!.*\beval\b)(?!.*\bFunction\b).*$",  # No eval/Function
        "java_17": r"^(?!.*\bRuntime\b).*$",  # No Runtime.exec()
        "cpp_20": r"^(?!.*\bsystem\b).*$",  # No system() calls
        "go_1_21": r"^(?!.*\bexec\.Command\b).*$"  # No os/exec
    }
    
    @classmethod
    def validate_syntax(cls, code: str, language_id: str) -> Tuple[bool, str]:
        """
        Main validation entry point.
        Routes to language-specific validator.
        
        Returns:
            (True, "") if valid
            (False, "error message") if invalid
        """
        if not code or not code.strip():
            return True, ""  # Empty code is valid (no-op)
        
        validators = {
            "python_3": cls._validate_python,
            "javascript_es6": cls._validate_javascript,
            "java_17": cls._validate_java,
            "cpp_20": cls._validate_cpp,
            "go_1_21": cls._validate_go
        }
        
        validator = validators.get(language_id)
        if not validator:
            # Unknown language - skip validation (allow it)
            return True, f"No validator for {language_id}"
        
        return validator(code)
    
    @staticmethod
    def _validate_python(code: str) -> Tuple[bool, str]:
        """
        Python validation using AST parser (no dependencies needed).
        """
        try:
            ast.parse(code)
            return True, ""
        except SyntaxError as e:
            return False, f"Line {e.lineno}: {e.msg}"
        except Exception as e:
            return False, str(e)
    
    @staticmethod
    def _validate_javascript(code: str) -> Tuple[bool, str]:
        """
        JavaScript validation using Node.js (if available).
        Falls back to basic regex if Node.js not installed.
        """
        # Try Node.js syntax check
        try:
            with tempfile.NamedTemporaryFile(mode='w', suffix='.js', delete=False, encoding='utf-8') as f:
                f.write(code)
                temp_path = f.name
            
            result = subprocess.run(
                ['node', '--check', temp_path],
                capture_output=True,
                text=True,
                timeout=2
            )
            
            os.unlink(temp_path)
            
            if result.returncode == 0:
                return True, ""
            else:
                # Extract meaningful error
                error = result.stderr.split('\n')[0] if result.stderr else "Syntax error"
                return False, error
        
        except FileNotFoundError:
            # Node.js not installed - use basic validation
            print("⚠️ Node.js not found, using basic JS validation")
            if re.search(r'[{}();]', code):  # Has basic JS syntax
                return True, "Basic validation only"
            return False, "Invalid JavaScript structure"
        
        except Exception as e:
            return False, str(e)
    
    @staticmethod
    def _validate_java(code: str) -> Tuple[bool, str]:
        """
        Java validation using javac (if available).
        Falls back to class detection if javac missing.
        """
        # Wrap in class if needed
        if "class" not in code and "interface" not in code:
            code = f"public class TempValidation {{ {code} }}"
        
        try:
            with tempfile.NamedTemporaryFile(mode='w', suffix='.java', delete=False, encoding='utf-8') as f:
                f.write(code)
                temp_path = f.name
            
            result = subprocess.run(
                ['javac', '-Xdiags:verbose', temp_path],
                capture_output=True,
                text=True,
                timeout=3
            )
            
            # Cleanup
            os.unlink(temp_path)
            class_file = temp_path.replace('.java', '.class')
            if os.path.exists(class_file):
                os.unlink(class_file)
            
            if result.returncode == 0:
                return True, ""
            else:
                error = result.stderr.split('\n')[0] if result.stderr else "Syntax error"
                return False, error
        
        except FileNotFoundError:
            # javac not installed - basic validation
            print("⚠️ javac not found, using basic Java validation")
            if re.search(r'(class|public|private|void)', code):
                return True, "Basic validation only"
            return False, "Invalid Java structure"
        
        except Exception as e:
            return False, str(e)
    
    @staticmethod
    def _validate_cpp(code: str) -> Tuple[bool, str]:
        """
        C++ validation using g++ (if available).
        Falls back to basic include detection.
        """
        try:
            with tempfile.NamedTemporaryFile(mode='w', suffix='.cpp', delete=False, encoding='utf-8') as f:
                f.write(code)
                temp_path = f.name
            
            result = subprocess.run(
                ['g++', '-fsyntax-only', '-std=c++20', temp_path],
                capture_output=True,
                text=True,
                timeout=3
            )
            
            os.unlink(temp_path)
            
            if result.returncode == 0:
                return True, ""
            else:
                error = result.stderr.split('\n')[0] if result.stderr else "Syntax error"
                return False, error
        
        except FileNotFoundError:
            # g++ not installed - basic validation
            print("⚠️ g++ not found, using basic C++ validation")
            if re.search(r'(#include|int|void|return)', code):
                return True, "Basic validation only"
            return False, "Invalid C++ structure"
        
        except Exception as e:
            return False, str(e)
    
    @staticmethod
    def _validate_go(code: str) -> Tuple[bool, str]:
        """
        Go validation using go build (if available).
        """
        # Wrap in package if needed
        if "package" not in code:
            code = f"package main\n\n{code}"
        
        try:
            with tempfile.NamedTemporaryFile(mode='w', suffix='.go', delete=False, encoding='utf-8') as f:
                f.write(code)
                temp_path = f.name
            
            result = subprocess.run(
                ['go', 'build', '-o', os.devnull, temp_path],
                capture_output=True,
                text=True,
                timeout=3
            )
            
            os.unlink(temp_path)
            
            if result.returncode == 0:
                return True, ""
            else:
                error = result.stderr.split('\n')[0] if result.stderr else "Syntax error"
                return False, error
        
        except FileNotFoundError:
            # Go not installed - basic validation
            print("⚠️ Go not found, using basic Go validation")
            if re.search(r'(package|func|import)', code):
                return True, "Basic validation only"
            return False, "Invalid Go structure"
        
        except Exception as e:
            return False, str(e)
    
    @staticmethod
    def generate_content_hash(question_data: Dict) -> str:
        """
        Creates unique fingerprint for deduplication.
        
        Loophole Fix #12: Hashes OUTPUT (question content), not INPUT (prompt)
        This ensures "Loops", "For Loops", "Python Loops" all deduplicate correctly
        
        Hash Components:
        - Question text (normalized)
        - Code snippet (whitespace-removed)
        - All option texts (sorted)
        - Language and difficulty (prevent cross-language/difficulty collisions)
        
        Returns:
            32-character hex string (MD5)
        """
        # 1. Normalize question text
        q_text = question_data.get('question_text', '').strip().lower()
        
        # 2. Normalize code (remove all whitespace)
        code = question_data.get('code_snippet', '') or ''
        norm_code = "".join(code.split())
        
        # 3. Get options text (sorted by ID to ensure consistency)
        options = question_data.get('options', [])
        sorted_opts = sorted(options, key=lambda x: x.get('id', ''))
        opt_texts = "".join([o.get('text', '').strip() for o in sorted_opts])
        
        # 4. Include language and difficulty to prevent collisions
        lang = question_data.get('language_id', 'unknown')
        diff = str(question_data.get('difficulty', 0.5))
        
        # 5. Combine and hash
        content = f"{lang}_{diff}_{q_text}{norm_code}{opt_texts}"
        return hashlib.md5(content.encode('utf-8')).hexdigest()
    
    @staticmethod
    def validate_option_quality(question_data: Dict) -> Tuple[bool, str]:
        """
        Validate that options meet quality standards.
        
        Loophole Fix #10: Rejects "None of the above" and lazy options
        
        Checks:
        - No "None of the above" options
        - No "All of the above" options
        - No "I don't know" options
        - All distractors are specific, not generic
        
        Returns:
            (True, "") if valid
            (False, "reason") if invalid
        """
        options = question_data.get('options', [])
        
        forbidden_patterns = [
            r'none\s+of\s+the\s+above',
            r'all\s+of\s+the\s+above',
            r'i\s+don\'?t\s+know',
            r'cannot\s+determine',
            r'not\s+enough\s+information',
            r'^error$',  # Generic "error" without specifics
            r'^exception$',  # Generic "exception"
        ]
        
        for opt in options:
            text = opt.get('text', '').lower().strip()
            original_text = opt.get('text', '').strip()
            
            for pattern in forbidden_patterns:
                if re.search(pattern, text):
                    return False, f"Forbidden option pattern: '{opt['text']}'"
            
            # Allow short answers if they are:
            # 1. Pure numbers: "2", "42"
            # 2. Contain digits: "2 4", "2.5", "A2"
            # 3. Common valid short answers: "Yes", "No", "True", "False"
            # 4. Single uppercase letter: "A", "B", "C" (option references)
            if len(text) < 5:
                has_digit = any(c.isdigit() for c in text)
                is_common_short = text in ['yes', 'no', 'true', 'false']
                is_single_letter = len(original_text) == 1 and original_text.isupper()
                
                if not (has_digit or is_common_short or is_single_letter):
                    return False, f"Option too vague: '{opt['text']}'"
        
        return True, ""
