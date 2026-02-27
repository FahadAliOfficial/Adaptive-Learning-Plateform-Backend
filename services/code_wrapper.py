"""
Code Wrapper Service
Automatically wraps code snippets in language-appropriate boilerplate for execution.
"""

import re
from typing import Optional


class CodeWrapper:
    """Service for wrapping code snippets in executable boilerplate."""
    
    @staticmethod
    def wrap_python(snippet: str, expected_output: Optional[str] = None) -> str:
        """
        Wrap Python code snippet.
        
        Args:
            snippet: Python code snippet
            expected_output: Expected output value (if snippet is expression)
            
        Returns:
            Executable Python program
        """
        # Check if snippet is already a complete program
        has_main = "if __name__" in snippet or "def main" in snippet
        has_import = snippet.strip().startswith(("import ", "from "))
        has_print = "print(" in snippet
        
        # If it looks complete, return as-is
        if (has_main or has_print) and len(snippet.split('\n')) > 3:
            return snippet
        
        # Check if it's just an expression (single line, no statements)
        lines = [line.strip() for line in snippet.strip().split('\n') if line.strip()]
        if len(lines) == 1 and not any(keyword in snippet for keyword in ['=', 'def ', 'class ', 'if ', 'for ', 'while ']):
            # Single expression - wrap in print
            return f"print({snippet.strip()})"
        
        # Wrap snippet with print if needed
        if not has_print:
            # Add print for last expression or variable
            return f"{snippet}\n"
        
        return snippet
    
    @staticmethod
    def wrap_javascript(snippet: str, expected_output: Optional[str] = None) -> str:
        """
        Wrap JavaScript code snippet.
        
        Args:
            snippet: JavaScript code snippet
            expected_output: Expected output value
            
        Returns:
            Executable JavaScript program
        """
        # Check if snippet already has console.log
        has_console = "console.log" in snippet
        
        # If complete program, return as-is
        if has_console and len(snippet.split('\n')) > 2:
            return snippet
        
        # Check if it's a simple expression
        lines = [line.strip() for line in snippet.strip().split('\n') if line.strip()]
        if len(lines) == 1 and not any(keyword in snippet for keyword in ['=', 'function ', 'const ', 'let ', 'var ', 'if ', 'for ', 'while ']):
            return f"console.log({snippet.strip()});"
        
        # If no console.log, add one at the end
        if not has_console:
            return f"{snippet}\n"
        
        return snippet
    
    @staticmethod
    def wrap_cpp(snippet: str, expected_output: Optional[str] = None) -> str:
        """
        Wrap C++ code snippet.
        
        Args:
            snippet: C++ code snippet
            expected_output: Expected output value
            
        Returns:
            Executable C++ program
        """
        # Check if already complete program
        has_main = "int main" in snippet or "void main" in snippet
        has_includes = "#include" in snippet
        
        if has_main and has_includes:
            return snippet
        
        # Build complete program
        includes = "#include <iostream>\n"
        if "string" in snippet.lower():
            includes += "#include <string>\n"
        if "vector" in snippet.lower():
            includes += "#include <vector>\n"
        
        # Add using namespace if not present
        using_namespace = ""
        if "using namespace" not in snippet:
            using_namespace = "using namespace std;\n"
        
        # Check if snippet is just an expression or statement
        snippet_stripped = snippet.strip()
        if not has_main:
            # Wrap in main
            return f"""{includes}{using_namespace}
int main() {{
    {snippet_stripped}
    return 0;
}}"""
        
        return snippet
    
    @staticmethod
    def wrap_java(snippet: str, expected_output: Optional[str] = None) -> str:
        """
        Wrap Java code snippet.
        
        Args:
            snippet: Java code snippet
            expected_output: Expected output value
            
        Returns:
            Executable Java program
        """
        import re
        
        # Check if already complete program
        has_class = "class " in snippet and "public static void main" in snippet
        
        if has_class:
            # Fix: If it's a public class with a name other than "Main", rename it to "Main"
            # This is because Judge0 saves it as Main.java
            public_class_match = re.search(r'public\s+class\s+(\w+)', snippet)
            if public_class_match:
                class_name = public_class_match.group(1)
                if class_name != "Main":
                    # Replace the class name with "Main"
                    snippet = re.sub(
                        r'public\s+class\s+' + class_name + r'\s*\{',
                        'public class Main {',
                        snippet
                    )
            return snippet
        
        # Wrap in Main class with main method
        snippet_stripped = snippet.strip()
        
        # Check if snippet is just an expression
        if not any(keyword in snippet for keyword in ['=', 'if ', 'for ', 'while ', 'System.out']):
            # Simple expression - wrap in println
            return f"""public class Main {{
    public static void main(String[] args) {{
        System.out.println({snippet_stripped});
    }}
}}"""
        
        # Statement or block - wrap in main
        return f"""public class Main {{
    public static void main(String[] args) {{
        {snippet_stripped}
    }}
}}"""
    
    @staticmethod
    def wrap_go(snippet: str, expected_output: Optional[str] = None) -> str:
        """
        Wrap Go code snippet.
        
        Args:
            snippet: Go code snippet
            expected_output: Expected output value
            
        Returns:
            Executable Go program
        """
        # Check if already complete program
        has_package = "package main" in snippet
        has_main = "func main()" in snippet
        
        if has_package and has_main:
            return snippet
        
        # Add imports
        imports = 'import "fmt"\n'
        if "strings." in snippet:
            imports = 'import (\n    "fmt"\n    "strings"\n)\n'
        
        # Wrap in main
        snippet_stripped = snippet.strip()
        
        # Check if snippet is just an expression
        if not any(keyword in snippet for keyword in [':=', '=', 'if ', 'for ', 'fmt.']):
            # Simple expression - wrap in Println
            return f"""package main

{imports}
func main() {{
    fmt.Println({snippet_stripped})
}}"""
        
        # Statement or block
        return f"""package main

{imports}
func main() {{
    {snippet_stripped}
}}"""
    
    @staticmethod
    def wrap_code(
        language_id: str, 
        snippet: str, 
        expected_output: Optional[str] = None
    ) -> str:
        """
        Wrap code snippet based on language.
        
        Args:
            language_id: Language identifier (e.g., "python_3")
            snippet: Code snippet to wrap
            expected_output: Expected output value (optional)
            
        Returns:
            Executable code
            
        Raises:
            ValueError: If language not supported
        """
        wrappers = {
            "python_3": CodeWrapper.wrap_python,
            "javascript_es6": CodeWrapper.wrap_javascript,
            "cpp_20": CodeWrapper.wrap_cpp,
            "java_17": CodeWrapper.wrap_java,
            "go_1_21": CodeWrapper.wrap_go,
        }
        
        wrapper_func = wrappers.get(language_id)
        if wrapper_func is None:
            raise ValueError(f"Unsupported language: {language_id}")
        
        return wrapper_func(snippet, expected_output)
    
    @staticmethod
    def is_already_wrapped(language_id: str, code: str) -> bool:
        """
        Check if code is already a complete program.
        
        Args:
            language_id: Language identifier
            code: Code to check
            
        Returns:
            True if code is already complete
        """
        checks = {
            "python_3": lambda c: "if __name__" in c or ("print(" in c and len(c.split('\n')) > 2),
            "javascript_es6": lambda c: "console.log" in c and len(c.split('\n')) > 2,
            "cpp_20": lambda c: "int main" in c and "#include" in c,
            "java_17": lambda c: "class " in c and "public static void main" in c,
            "go_1_21": lambda c: "package main" in c and "func main()" in c,
        }
        
        check_func = checks.get(language_id)
        if check_func is None:
            return False
        
        return check_func(code)


def wrap_code(language_id: str, snippet: str, expected_output: Optional[str] = None) -> str:
    """
    Convenience function for wrapping code.
    
    Args:
        language_id: Language identifier
        snippet: Code snippet
        expected_output: Expected output value
        
    Returns:
        Executable code
    """
    return CodeWrapper.wrap_code(language_id, snippet, expected_output)
