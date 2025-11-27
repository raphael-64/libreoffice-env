"""Cell references and episode context management"""
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Dict

logger = logging.getLogger(__name__)

@dataclass
class CellRef:
    """Represents a spreadsheet cell reference."""
    row: int  # 0-indexed
    col: int  # 0-indexed
    
    @classmethod
    def from_a1(cls, cell: str) -> 'CellRef':
        """
        Parse A1 notation (e.g., 'B5' -> CellRef(row=4, col=1)).
        
        Args:
            cell: Cell reference in A1 notation (e.g., "A1", "B5", "AA10")
        
        Returns:
            CellRef with 0-indexed row and column
        """
        col_letter = ''.join(c for c in cell if c.isalpha()).upper()
        row_num = int(''.join(c for c in cell if c.isdigit())) - 1  # 0-indexed
        
        # Convert column letter to index (A=0, B=1, Z=25, AA=26, etc.)
        col_num = 0
        for i, char in enumerate(reversed(col_letter)):
            col_num += (ord(char) - ord('A') + 1) * (26 ** i)
        col_num -= 1  # 0-indexed
        
        return cls(row=row_num, col=col_num)
    
    def to_a1(self) -> str:
        """Convert to A1 notation (e.g., CellRef(4, 1) -> 'B5')."""
        col_letter = ''
        col = self.col + 1
        while col > 0:
            col -= 1
            col_letter = chr(65 + (col % 26)) + col_letter
            col //= 26
        return f"{col_letter}{self.row + 1}"
    
    def __str__(self) -> str:
        return self.to_a1()

@dataclass
class EpisodeContext:
    """Encapsulates all state for a single episode."""
    task_id: str
    run_dir: Path
    sandbox_manager: 'SandboxManager'  # type: ignore
    task_definition: dict
    
    def __post_init__(self):
        """Validate context."""
        if not self.run_dir.exists():
            raise ValueError(f"Run directory does not exist: {self.run_dir}")


class ContextRegistry:
    """Registry for episode contexts (supports single and multi-session)."""
    
    def __init__(self):
        self._contexts: Dict[str, EpisodeContext] = {}
        self._default_context: Optional[EpisodeContext] = None
    
    def register(self, context: EpisodeContext, session_id: Optional[str] = None) -> str:
        """Register a context."""
        if session_id is None:
            session_id = "default"
            self._default_context = context
        
        self._contexts[session_id] = context
        logger.info(f"Registered episode context: {session_id} (task={context.task_id})")
        return session_id
    
    def get(self, session_id: Optional[str] = None) -> EpisodeContext:
        """Get context by session_id, or default if None."""
        if session_id is None:
            if self._default_context is None:
                raise RuntimeError(
                    "No episode context set. Start an episode first using "
                    "start_episode() from episode_api"
                )
            return self._default_context
        
        if session_id not in self._contexts:
            raise RuntimeError(f"Session not found: {session_id}")
        return self._contexts[session_id]
    
    def clear(self, session_id: Optional[str] = None):
        """Clear a context."""
        if session_id is None:
            self._default_context = None
            self._contexts.pop("default", None)
            logger.info("Cleared default episode context")
        else:
            self._contexts.pop(session_id, None)
            logger.info(f"Cleared episode context: {session_id}")
    
    def has_context(self, session_id: Optional[str] = None) -> bool:
        """Check if a context exists."""
        if session_id is None:
            return self._default_context is not None
        return session_id in self._contexts


# global regstry instance
_context_registry = ContextRegistry()


def get_context(session_id: Optional[str] = None) -> EpisodeContext:
    """
    Get current episode context.
    
    If no context exists in registry (e.g., in MCP subprocess), 
    tries to create one from environment variables.
    """
    try:
        return _context_registry.get(session_id)
    except RuntimeError:
        import os
        task_id = os.environ.get('MCP_EPISODE_TASK_ID')
        run_dir = os.environ.get('MCP_EPISODE_RUN_DIR')
        container_id = os.environ.get('MCP_CONTAINER_ID')
        
        if task_id and run_dir and container_id:
            from orchestration.sandbox_manager import SandboxManager
            from orchestration.task_manager import TaskManager
            
            logger.info(f"Creating context from env vars: task={task_id}, container={container_id[:12]}")
            
            # Load task definition
            tm = TaskManager()
            task_def = tm.load_task(task_id)
            
            # Create sandbox manager and reconnect to existing container
            sandbox = SandboxManager(workspace_path=Path(run_dir))
            sandbox.reconnect_to_container(container_id)
            
            # Create context
            context = EpisodeContext(
                task_id=task_id,
                run_dir=Path(run_dir),
                sandbox_manager=sandbox,
                task_definition=task_def
            )
            
            # Register it
            set_context(context, session_id)
            
            return context
        
        # No context and no env vars - raise original error
        raise


def set_context(context: EpisodeContext, session_id: Optional[str] = None) -> str:
    """Set episode context."""
    return _context_registry.register(context, session_id)


def clear_context(session_id: Optional[str] = None):
    """Clear episode context."""
    _context_registry.clear(session_id)


def has_context(session_id: Optional[str] = None) -> bool:
    """Check if episode context exists."""
    return _context_registry.has_context(session_id)

