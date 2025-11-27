"""Simple API for episode management."""
import logging
from typing import Dict, Any, Optional

from orchestration.episode_runner import EpisodeRunner
from orchestration.task_manager import TaskManager
from utils import EpisodeContext, set_context, clear_context

logger = logging.getLogger(__name__)

# Singleton
_runner: Optional[EpisodeRunner] = None
_task_manager: Optional[TaskManager] = None


def _get_runner() -> EpisodeRunner:
    global _runner
    if _runner is None:
        _runner = EpisodeRunner()
    return _runner


def _get_task_manager() -> TaskManager:
    global _task_manager
    if _task_manager is None:
        _task_manager = TaskManager()
    return _task_manager


def start_episode(task_id: str) -> Dict[str, Any]:
    """Start episode (creates container, auto-increments run number)."""
    runner = _get_runner()
    tm = _get_task_manager()
    
    sandbox, run_dir, task_def = runner.start_episode(task_id)
    
    context = EpisodeContext(
        task_id=task_id,
        run_dir=run_dir,
        sandbox_manager=sandbox,
        task_definition=task_def
    )
    set_context(context)
    
    return {
        "task_id": task_id,
        "description": task_def["description"],
        "files": list(tm.get_initial_files(task_id).keys()),
        "run_dir": str(run_dir),
        "container_id": sandbox.container_id,
        "time_limit": task_def.get("time_limit_seconds", 600)
    }


def end_episode(grade: bool = False, cleanup: bool = False) -> Optional[Dict[str, Any]]:
    """End episode (destroys container)."""
    runner = _get_runner()
    result = runner.end_episode(grade=grade, cleanup=cleanup)
    clear_context()
    return result


def list_tasks() -> list[str]:
    """List available tasks."""
    return _get_task_manager().list_tasks()


def get_task_info(task_id: str) -> Dict[str, Any]:
    """Get task info without starting episode."""
    return _get_task_manager().load_task(task_id)

