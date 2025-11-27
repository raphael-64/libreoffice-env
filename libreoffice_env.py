"""
LibreOffice RL Environment - Main API

Clean interface for RL training on spreadsheet tasks.
"""
from pathlib import Path
from typing import Dict, Any, Optional
from orchestration.env_runner import EpisodeRunner
from orchestration.task_manager import TaskManager


class LibreOfficeEnv:
    """
    LibreOffice RL Environment.
    
    Usage:
        env = LibreOfficeEnv()
        state = env.reset("sales_totals")
        result = env.step(agent_action)
        score = env.get_reward()
    """
    
    def __init__(self, base_image: str = "libreoffice-sandbox:latest"):
        """Initialize the environment."""
        self.runner = EpisodeRunner(base_image=base_image)
        self.task_manager = TaskManager()
        self.current_task = None
        self.current_run_dir = None
    
    def list_tasks(self) -> list[str]:
        """List all available tasks."""
        return self.task_manager.list_tasks()
    
    def reset(self, task_id: str, episode_num: Optional[int] = None) -> Dict[str, Any]:
        """
        Start a new episode.
        
        Args:
            task_id: Task to run
            episode_num: Episode number (auto-increments if None)
        
        Returns:
            Initial state dict with task description and available files
        """
        sandbox, run_dir, task_def = self.runner.start_episode(task_id, episode_num)
        
        self.current_task = task_id
        self.current_run_dir = run_dir
        
        # Set globals for MCP server
        import mcp_server
        mcp_server.sandbox_manager = sandbox
        mcp_server.current_task_id = task_id
        mcp_server.current_run_dir = run_dir
        mcp_server.task_manager = self.task_manager
        
        return {
            "task_id": task_id,
            "description": task_def["description"],
            "files": list(self.task_manager.get_initial_files(task_id).keys()),
            "run_dir": str(run_dir),
            "time_limit": task_def.get("time_limit_seconds", 600)
        }
    
    def get_reward(self) -> float:
        """
        Get reward for current episode (triggers grading).
        
        Returns:
            Score between 0.0 and 1.0
        """
        result = self.runner.end_episode(grade=True, cleanup=False)
        return result["score"] if result else 0.0
    
    def close(self, cleanup: bool = True):
        """
        End episode and cleanup.
        
        Args:
            cleanup: If True, delete run directory to save space
        """
        self.runner.end_episode(grade=False, cleanup=cleanup)
        self.current_task = None
        self.current_run_dir = None

