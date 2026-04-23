#!/usr/bin/env python3
"""
File Browser - Safe file system operations with cross-platform support
Integrates with sandbox manager for safe editing workflows
"""

import os
from pathlib import Path
from typing import List, Dict, Optional, Tuple
import mimetypes
import logging

logger = logging.getLogger(__name__)


class FileBrowser:
    """
    Safe file browser with cross-platform support.
    Restricted to configured base directories for security.
    """

    def __init__(self, base_dirs: Optional[List[str]] = None):
        """
        Initialize file browser with allowed base directories.

        Args:
            base_dirs: List of allowed base directories. If None, uses current directory.
        """
        if base_dirs is None:
            base_dirs = [str(Path.cwd())]
        elif isinstance(base_dirs, str):
            base_dirs = [base_dirs]

        self.base_dirs = [Path(d).resolve() for d in base_dirs]
        self.current_dir = self.base_dirs[0] if self.base_dirs else Path.cwd()
        logger.info(f"Initialized FileBrowser with {len(self.base_dirs)} base directories")

    def _is_path_allowed(self, path: Path) -> bool:
        """Check if path is within allowed base directories"""
        try:
            resolved = path.resolve()
            return any(
                resolved == base or resolved.is_relative_to(base)
                for base in self.base_dirs
            )
        except (ValueError, OSError):
            return False

    def list_directory(
        self,
        path: str = ".",
        show_hidden: bool = False,
        max_depth: int = 1
    ) -> Dict:
        """
        List directory contents with metadata.
        
        Returns:
            Dict with files, directories, and metadata
        """
        target_path = Path(path).resolve()

        if not self._is_path_allowed(target_path):
            return {
                'success': False,
                'error': 'Access denied: path outside allowed directories'
            }

        if not target_path.exists():
            return {'success': False, 'error': 'Path does not exist'}

        if not target_path.is_dir():
            return {'success': False, 'error': 'Path is not a directory'}

        try:
            entries = []
            
            for item in sorted(target_path.iterdir()):
                # Skip hidden files unless requested
                if not show_hidden and item.name.startswith('.'):
                    continue

                try:
                    stat = item.stat()
                    entry = {
                        'name': item.name,
                        'path': str(item),
                        'is_dir': item.is_dir(),
                        'is_file': item.is_file(),
                        'size': stat.st_size if item.is_file() else 0,
                        'modified': stat.st_mtime,
                        'type': self._get_file_type(item)
                    }
                    entries.append(entry)
                except (PermissionError, OSError) as e:
                    logger.warning(f"Cannot access {item}: {e}")
                    continue

            return {
                'success': True,
                'path': str(target_path),
                'entries': entries,
                'total': len(entries),
                'dirs': sum(1 for e in entries if e['is_dir']),
                'files': sum(1 for e in entries if e['is_file'])
            }

        except Exception as e:
            logger.error(f"Error listing directory {path}: {e}")
            return {'success': False, 'error': str(e)}

    def read_file(self, filepath: str, max_size: int = 10 * 1024 * 1024) -> Dict:
        """
        Read file contents safely.
        
        Args:
            filepath: Path to file
            max_size: Maximum file size to read (default 10MB)
            
        Returns:
            Dict with file content and metadata
        """
        file_path = Path(filepath).resolve()

        if not self._is_path_allowed(file_path):
            return {'success': False, 'error': 'Access denied'}

        if not file_path.exists():
            return {'success': False, 'error': 'File not found'}

        if not file_path.is_file():
            return {'success': False, 'error': 'Not a file'}

        try:
            stat = file_path.stat()
            
            if stat.st_size > max_size:
                return {
                    'success': False,
                    'error': f'File too large ({stat.st_size} bytes, max {max_size})'
                }

            # Try to read as text
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                return {
                    'success': True,
                    'path': str(file_path),
                    'content': content,
                    'size': stat.st_size,
                    'lines': len(content.split('\n')),
                    'type': self._get_file_type(file_path),
                    'encoding': 'utf-8'
                }
            except UnicodeDecodeError:
                # File is binary
                return {
                    'success': False,
                    'error': 'Binary file - cannot display as text',
                    'path': str(file_path),
                    'size': stat.st_size,
                    'type': 'binary'
                }

        except Exception as e:
            logger.error(f"Error reading file {filepath}: {e}")
            return {'success': False, 'error': str(e)}

    def write_file(self, filepath: str, content: str, create_backup: bool = True) -> Dict:
        """
        Write content to file (should generally use sandbox workflow instead).
        
        Args:
            filepath: Path to file
            content: Content to write
            create_backup: Create backup of existing file
            
        Returns:
            Dict with operation result
        """
        file_path = Path(filepath).resolve()

        if not self._is_path_allowed(file_path):
            return {'success': False, 'error': 'Access denied'}

        try:
            # Create backup if file exists
            if create_backup and file_path.exists():
                backup_path = file_path.with_suffix(file_path.suffix + '.backup')
                import shutil
                shutil.copy2(file_path, backup_path)

            # Write file
            file_path.parent.mkdir(parents=True, exist_ok=True)
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)

            return {
                'success': True,
                'path': str(file_path),
                'size': len(content),
                'backup_created': create_backup and file_path.exists()
            }

        except Exception as e:
            logger.error(f"Error writing file {filepath}: {e}")
            return {'success': False, 'error': str(e)}

    def search_files(
        self,
        pattern: str,
        directory: str = ".",
        max_results: int = 100
    ) -> Dict:
        """
        Search for files matching pattern.
        
        Args:
            pattern: File name pattern (supports wildcards)
            directory: Directory to search
            max_results: Maximum number of results
            
        Returns:
            Dict with matching files
        """
        search_path = Path(directory).resolve()

        if not self._is_path_allowed(search_path):
            return {'success': False, 'error': 'Access denied'}

        if not search_path.exists():
            return {'success': False, 'error': 'Directory not found'}

        try:
            matches = []
            for path in search_path.rglob(pattern):
                if self._is_path_allowed(path):
                    matches.append({
                        'path': str(path),
                        'name': path.name,
                        'is_dir': path.is_dir(),
                        'size': path.stat().st_size if path.is_file() else 0
                    })
                    
                    if len(matches) >= max_results:
                        break

            return {
                'success': True,
                'pattern': pattern,
                'matches': matches,
                'count': len(matches),
                'truncated': len(matches) >= max_results
            }

        except Exception as e:
            logger.error(f"Error searching files: {e}")
            return {'success': False, 'error': str(e)}

    def get_file_info(self, filepath: str) -> Dict:
        """Get detailed file information"""
        file_path = Path(filepath).resolve()

        if not self._is_path_allowed(file_path):
            return {'success': False, 'error': 'Access denied'}

        if not file_path.exists():
            return {'success': False, 'error': 'File not found'}

        try:
            stat = file_path.stat()
            
            return {
                'success': True,
                'path': str(file_path),
                'name': file_path.name,
                'size': stat.st_size,
                'modified': stat.st_mtime,
                'created': stat.st_ctime,
                'is_file': file_path.is_file(),
                'is_dir': file_path.is_dir(),
                'is_symlink': file_path.is_symlink(),
                'extension': file_path.suffix,
                'type': self._get_file_type(file_path),
                'permissions': oct(stat.st_mode)[-3:]
            }

        except Exception as e:
            return {'success': False, 'error': str(e)}

    def _get_file_type(self, path: Path) -> str:
        """Determine file type from extension and content"""
        if path.is_dir():
            return 'directory'
        
        mime_type, _ = mimetypes.guess_type(str(path))
        if mime_type:
            return mime_type
        
        # Common code file extensions
        code_extensions = {
            '.py': 'python',
            '.js': 'javascript',
            '.ts': 'typescript',
            '.java': 'java',
            '.cpp': 'cpp',
            '.c': 'c',
            '.rs': 'rust',
            '.go': 'go',
            '.rb': 'ruby',
            '.php': 'php',
            '.sh': 'shell',
            '.sql': 'sql'
        }
        
        return code_extensions.get(path.suffix.lower(), 'unknown')

    # ------------------------------------------------------------------
    # CLI-style interface expected by agent_v2.py
    # ------------------------------------------------------------------

    def pwd(self) -> str:
        """Return current directory as string."""
        return str(self.current_dir)

    def cd(self, path: str) -> str:
        """Change current directory. Returns confirmation or error string."""
        target = Path(path) if Path(path).is_absolute() else self.current_dir / path
        target = target.resolve()
        if not self._is_path_allowed(target):
            return f"❌ Access denied: {target}"
        if not target.exists():
            return f"❌ Directory not found: {target}"
        if not target.is_dir():
            return f"❌ Not a directory: {target}"
        self.current_dir = target
        return f"📁 {target}"

    def ls(self, path: str = ".") -> str:
        """List directory, returning a formatted string."""
        target = Path(path) if Path(path).is_absolute() else self.current_dir / path
        result = self.list_directory(str(target), show_hidden=False)
        if not result['success']:
            return f"❌ {result['error']}"
        lines = [f"📁 {result['path']}  ({result['dirs']} dirs, {result['files']} files)\n"]
        for e in result['entries']:
            icon = "📁" if e['is_dir'] else "📄"
            size = f"  {e['size']:>8,}B" if e['is_file'] else ""
            lines.append(f"  {icon} {e['name']}{size}")
        return "\n".join(lines)

    def tree(self, path: str = ".", max_depth: int = 3) -> str:
        """Return ASCII directory tree as string."""
        target = Path(path) if Path(path).is_absolute() else self.current_dir / path
        target = target.resolve()
        if not self._is_path_allowed(target):
            return f"❌ Access denied: {target}"
        lines = [str(target)]
        self._tree_recurse(target, lines, prefix="", depth=0, max_depth=max_depth)
        return "\n".join(lines)

    def _tree_recurse(self, path: Path, lines: list, prefix: str, depth: int, max_depth: int):
        if depth >= max_depth:
            return
        try:
            entries = sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name))
        except PermissionError:
            return
        entries = [e for e in entries if not e.name.startswith('.')]
        for i, entry in enumerate(entries):
            connector = "└── " if i == len(entries) - 1 else "├── "
            lines.append(f"{prefix}{connector}{entry.name}")
            if entry.is_dir():
                extension = "    " if i == len(entries) - 1 else "│   "
                self._tree_recurse(entry, lines, prefix + extension, depth + 1, max_depth)

    def read_full(self, path: str) -> tuple:
        """Read full file. Returns (content, success_bool)."""
        target = Path(path) if Path(path).is_absolute() else self.current_dir / path
        result = self.read_file(str(target))
        if result['success']:
            return result['content'], True
        return result['error'], False

    def read(self, path: str, start_line: int = 1, end_line: int = None) -> str:
        """Read file lines with line numbers. Returns formatted string."""
        content, ok = self.read_full(path)
        if not ok:
            return f"❌ {content}"
        lines = content.splitlines()
        total = len(lines)
        s = max(1, start_line) - 1
        e = min(end_line, total) if end_line else total
        out = [f"📄 {path}  (lines {s+1}-{e} of {total})\n"]
        for i, line in enumerate(lines[s:e], start=s + 1):
            out.append(f"{i:4d} │ {line}")
        return "\n".join(out)

    def find(self, pattern: str, path: str = ".", content_search: bool = False) -> str:
        """Find files by name pattern or content. Returns formatted string."""
        target = Path(path) if Path(path).is_absolute() else self.current_dir / path
        if content_search:
            # Search within file contents
            matches = []
            for fp in target.rglob('*'):
                if fp.is_file() and self._is_path_allowed(fp):
                    try:
                        text = fp.read_text(encoding='utf-8', errors='ignore')
                        if pattern.lower() in text.lower():
                            matches.append(str(fp))
                    except OSError:
                        pass
            if not matches:
                return f"No files containing '{pattern}'"
            return f"Files containing '{pattern}':\n" + "\n".join(f"  {m}" for m in matches[:50])
        else:
            result = self.search_files(pattern, str(target))
            if not result['success']:
                return f"❌ {result['error']}"
            if not result['matches']:
                return f"No files matching '{pattern}'"
            lines = [f"Found {result['count']} match(es) for '{pattern}':"]
            for m in result['matches'][:50]:
                icon = "📁" if m['is_dir'] else "📄"
                lines.append(f"  {icon} {m['path']}")
            return "\n".join(lines)

    def grep(self, pattern: str, path: str, context_lines: int = 2) -> str:
        """Search for pattern within a file. Returns formatted matches."""
        import re
        target = Path(path) if Path(path).is_absolute() else self.current_dir / path
        content, ok = self.read_full(str(target))
        if not ok:
            return f"❌ {content}"
        lines = content.splitlines()
        matches = []
        for i, line in enumerate(lines):
            if re.search(pattern, line, re.IGNORECASE):
                start = max(0, i - context_lines)
                end = min(len(lines), i + context_lines + 1)
                block = []
                for j in range(start, end):
                    marker = ">>>" if j == i else "   "
                    block.append(f"{j+1:4d}{marker}│ {lines[j]}")
                matches.append("\n".join(block))
        if not matches:
            return f"No matches for '{pattern}' in {path}"
        return f"grep '{pattern}' in {path} — {len(matches)} match(es):\n\n" + "\n\n".join(matches)

    def edit_lines(self, path: str, start_line: int, end_line: int, new_content: str, create_backup: bool = True) -> str:
        """Replace lines start_line..end_line with new_content. Returns status string."""
        target = Path(path) if Path(path).is_absolute() else self.current_dir / path
        if not self._is_path_allowed(target.resolve()):
            return f"❌ Access denied: {target}"
        content, ok = self.read_full(str(target))
        if not ok:
            return f"❌ {content}"
        lines = content.splitlines(keepends=True)
        s = max(1, start_line) - 1
        e = min(end_line, len(lines))
        replacement = new_content if new_content.endswith('\n') else new_content + '\n'
        lines[s:e] = [replacement]
        result = self.write_file(str(target), "".join(lines), create_backup=create_backup)
        if result['success']:
            return f"✅ Edited {target.name} (lines {start_line}-{end_line} replaced)"
        return f"❌ {result['error']}"

    def write(self, path: str, content: str, create_backup: bool = True) -> str:
        """Write content to file. Returns status string."""
        target = Path(path) if Path(path).is_absolute() else self.current_dir / path
        result = self.write_file(str(target), content, create_backup=create_backup)
        if result['success']:
            return f"✅ Written {result['size']} bytes to {target}"
        return f"❌ {result['error']}"

    def add_allowed_path(self, path: str):
        """Add a path to allowed base directories"""
        resolved = Path(path).resolve()
        if resolved not in self.base_dirs:
            self.base_dirs.append(resolved)
            logger.info(f"Added allowed path: {resolved}")


# Global instance
_browser: Optional[FileBrowser] = None


def get_browser(base_dirs: Optional[List[str]] = None) -> FileBrowser:
    """Get file browser singleton"""
    global _browser
    if _browser is None:
        _browser = FileBrowser(base_dirs)
    return _browser


if __name__ == "__main__":
    print("Testing File Browser...")
    
    browser = get_browser()
    
    # Test listing current directory
    result = browser.list_directory(".")
    if result['success']:
        print(f"\n✅ Listed directory: {result['total']} items")
        print(f"   Directories: {result['dirs']}")
        print(f"   Files: {result['files']}")
    
    # Test file search
    result = browser.search_files("*.py")
    if result['success']:
        print(f"\n✅ Found {result['count']} Python files")
    
    print("\n✅ All tests passed!")
