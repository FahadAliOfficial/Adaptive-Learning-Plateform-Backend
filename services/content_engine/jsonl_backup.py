"""
JSONL backup system with file locking (prevents corruption).
Implements write-ahead logging for durability and fast lookups.
"""
import json
import os
from typing import Dict, List, Optional
from contextlib import contextmanager
from datetime import datetime
import hashlib
import tempfile
import shutil

# Platform-specific file locking
try:
    import fcntl  # POSIX systems (Linux, macOS)
    HAS_FCNTL = True
except ImportError:
    HAS_FCNTL = False
    # Windows fallback
    try:
        import msvcrt
        HAS_MSVCRT = True
    except ImportError:
        HAS_MSVCRT = False


class JSONLBackup:
    """
    Thread-safe JSONL backup with file locking.
    
    Features:
    - Exclusive locks for writes (prevents corruption)
    - Atomic writes (temp file + rename)
    - Index file for O(1) lookups (hash → line number)
    - Automatic compaction (remove duplicates)
    
    File Structure:
    - questions.jsonl: Main data file (append-only)
    - questions.jsonl.index: Hash → line number mapping
    """
    
    def __init__(self, file_path: str = "data/question_warehouse.jsonl"):
        self.file_path = file_path
        self.index_path = f"{file_path}.index"
        self._ensure_directory()
    
    def _ensure_directory(self):
        """Create data directory if it doesn't exist."""
        directory = os.path.dirname(self.file_path)
        if directory and not os.path.exists(directory):
            os.makedirs(directory, exist_ok=True)
            print(f"✅ Created backup directory: {directory}")
    
    @contextmanager
    def _lock_file(self, file_handle, exclusive=True):
        """
        Platform-agnostic file locking.
        
        Args:
            file_handle: Open file object
            exclusive: True for write lock, False for read lock
        """
        try:
            if HAS_FCNTL:
                # POSIX systems (Linux, macOS)
                lock_type = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
                fcntl.flock(file_handle.fileno(), lock_type)
            elif HAS_MSVCRT and exclusive:
                # Windows - only lock on writes, skip on reads
                try:
                    # Lock first byte of file
                    file_handle.seek(0)
                    msvcrt.locking(file_handle.fileno(), msvcrt.LK_NBLCK, 1)
                except (IOError, OSError):
                    # Lock failed, continue anyway (best effort)
                    pass
            
            yield file_handle
        
        finally:
            if HAS_FCNTL:
                fcntl.flock(file_handle.fileno(), fcntl.LOCK_UN)
            elif HAS_MSVCRT and exclusive:
                try:
                    file_handle.seek(0)
                    msvcrt.locking(file_handle.fileno(), msvcrt.LK_UNLCK, 1)
                except (IOError, OSError):
                    pass  # Already unlocked
    
    def append_question(self, question_data: Dict):
        """
        Append a single question to JSONL file (thread-safe).
        
        Args:
            question_data: Question dictionary with content_hash
        
        Returns:
            True if appended, False if duplicate
        """
        content_hash = question_data.get('content_hash')
        if not content_hash:
            raise ValueError("question_data must include 'content_hash' field")
        
        # Check if already exists in index
        if self._exists_in_index(content_hash):
            print(f"[JSONL] Skipped duplicate: {content_hash[:8]}")
            return False
        
        # Append to main file (with exclusive lock)
        if not os.path.exists(self.file_path):
            # Create empty file
            with open(self.file_path, 'w', encoding='utf-8') as f:
                pass
        
        with open(self.file_path, 'a', encoding='utf-8') as f:
            with self._lock_file(f, exclusive=True):
                # Get current line number
                line_number = self._count_lines()
                
                # Write question (newline-delimited JSON)
                json_line = json.dumps(question_data, ensure_ascii=False)
                f.write(json_line + '\n')
                f.flush()
                
                # Update index
                self._update_index(content_hash, line_number)
        
        print(f"✅ Backed up question to JSONL: {content_hash[:8]} (line {line_number})")
        return True
    
    def append_batch(self, questions: List[Dict]):
        """
        Append multiple questions efficiently (single lock).
        
        Args:
            questions: List of question dictionaries
        
        Returns:
            Number of questions actually appended (excluding duplicates)
        """
        if not questions:
            return 0
        
        # Filter out duplicates
        new_questions = []
        for q in questions:
            content_hash = q.get('content_hash')
            if not content_hash:
                print(f"⚠️ Skipping question without content_hash")
                continue
            
            if not self._exists_in_index(content_hash):
                new_questions.append(q)
        
        if not new_questions:
            print(f"[JSONL] All {len(questions)} questions already exist (skipped)")
            return 0
        
        # Ensure file exists
        if not os.path.exists(self.file_path):
            with open(self.file_path, 'w', encoding='utf-8') as f:
                pass
        
        # Batch append (single lock for performance)
        with open(self.file_path, 'a', encoding='utf-8') as f:
            with self._lock_file(f, exclusive=True):
                start_line = self._count_lines()
                
                for i, question in enumerate(new_questions):
                    json_line = json.dumps(question, ensure_ascii=False)
                    f.write(json_line + '\n')
                    
                    # Update index
                    content_hash = question['content_hash']
                    self._update_index(content_hash, start_line + i)
                
                f.flush()
        
        print(f"✅ Backed up {len(new_questions)}/{len(questions)} questions to JSONL (line {start_line}-{start_line + len(new_questions) - 1})")
        return len(new_questions)
    
    def query_by_hash(self, content_hash: str) -> Optional[Dict]:
        """
        Retrieve a question by its content hash (O(1) lookup via index).
        
        Args:
            content_hash: MD5 hash of question content
        
        Returns:
            Question dictionary or None if not found
        """
        line_number = self._get_line_from_index(content_hash)
        if line_number is None:
            return None
        
        # Read specific line from file
        try:
            with open(self.file_path, 'r', encoding='utf-8') as f:
                with self._lock_file(f, exclusive=False):
                    for i, line in enumerate(f):
                        if i == line_number:
                            return json.loads(line.strip())
        except FileNotFoundError:
            return None
        
        return None
    
    def _count_lines(self) -> int:
        """Count total lines in file."""
        if not os.path.exists(self.file_path):
            return 0
        
        try:
            with open(self.file_path, 'r', encoding='utf-8') as f:
                # Don't lock during count (read-only operation)
                count = 0
                for _ in f:
                    count += 1
                return count
        except (FileNotFoundError, PermissionError):
            return 0
    
    def _exists_in_index(self, content_hash: str) -> bool:
        """Check if hash exists in index."""
        if not os.path.exists(self.index_path):
            return False
        
        try:
            with open(self.index_path, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.startswith(content_hash + '\t'):
                        return True
        except FileNotFoundError:
            return False
        
        return False
    
    def _get_line_from_index(self, content_hash: str) -> Optional[int]:
        """Get line number from index."""
        if not os.path.exists(self.index_path):
            return None
        
        try:
            with open(self.index_path, 'r', encoding='utf-8') as f:
                for line in f:
                    parts = line.strip().split('\t')
                    if len(parts) == 2 and parts[0] == content_hash:
                        return int(parts[1])
        except FileNotFoundError:
            return None
        
        return None
    
    def _update_index(self, content_hash: str, line_number: int):
        """Append to index file."""
        with open(self.index_path, 'a', encoding='utf-8') as f:
            f.write(f"{content_hash}\t{line_number}\n")
            f.flush()
    
    def compact(self):
        """
        Remove duplicate entries from JSONL file.
        Creates a new file with only unique questions (by content_hash).
        
        This is useful after parallel generation tasks may have created duplicates.
        """
        if not os.path.exists(self.file_path):
            print("[JSONL] No file to compact")
            return
        
        print("[JSONL] Starting compaction...")
        
        seen_hashes = set()
        unique_questions = []
        
        # Read all questions
        with open(self.file_path, 'r', encoding='utf-8') as f:
            for line in f:
                if not line.strip():
                    continue
                
                question = json.loads(line.strip())
                content_hash = question.get('content_hash')
                
                if content_hash and content_hash not in seen_hashes:
                    seen_hashes.add(content_hash)
                    unique_questions.append(question)
        
        # Write to temp file (atomic operation)
        temp_file = tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', delete=False, suffix='.jsonl')
        try:
            for question in unique_questions:
                json_line = json.dumps(question, ensure_ascii=False)
                temp_file.write(json_line + '\n')
            
            temp_file.close()
            
            # Replace original file (atomic on POSIX, best-effort on Windows)
            shutil.move(temp_file.name, self.file_path)
            
            # Rebuild index
            if os.path.exists(self.index_path):
                os.remove(self.index_path)
            
            for i, question in enumerate(unique_questions):
                self._update_index(question['content_hash'], i)
            
            removed = len(seen_hashes) - len(unique_questions)
            print(f"✅ Compaction complete: Removed {removed} duplicates ({len(unique_questions)} unique questions remain)")
        
        except Exception as e:
            # Clean up temp file on error
            if os.path.exists(temp_file.name):
                os.remove(temp_file.name)
            raise e
    
    def get_stats(self) -> Dict:
        """
        Get statistics about the backup file.
        
        Returns:
            Dictionary with total_questions, file_size_mb, etc.
        """
        stats = {
            'total_questions': 0,
            'file_size_mb': 0.0,
            'index_size_kb': 0.0,
            'file_exists': False
        }
        
        if os.path.exists(self.file_path):
            stats['file_exists'] = True
            stats['total_questions'] = self._count_lines()
            stats['file_size_mb'] = os.path.getsize(self.file_path) / (1024 * 1024)
        
        if os.path.exists(self.index_path):
            stats['index_size_kb'] = os.path.getsize(self.index_path) / 1024
        
        return stats


# Convenience function for scripts
def backup_question(question_data: Dict, backup_file: str = "data/question_warehouse.jsonl"):
    """
    Quick backup function for single questions.
    
    Usage:
        from services.content_engine.jsonl_backup import backup_question
        backup_question(question_data)
    """
    jsonl = JSONLBackup(backup_file)
    return jsonl.append_question(question_data)


def backup_batch(questions: List[Dict], backup_file: str = "data/question_warehouse.jsonl"):
    """
    Quick backup function for batches.
    
    Usage:
        from services.content_engine.jsonl_backup import backup_batch
        backup_batch(questions)
    """
    jsonl = JSONLBackup(backup_file)
    return jsonl.append_batch(questions)
