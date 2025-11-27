"""Task definition and loading."""
import json
import logging
from pathlib import Path
from typing import Dict, Any

logger = logging.getLogger(__name__)


class TaskManager:
    """Manages task definitions ."""
    
    def __init__(self, tasks_dir: Path | None = None):
        """
        Initialize task manager.
        
        Args:
            tasks_dir: Directory containing task definitions
        """
        if tasks_dir is None:
            tasks_dir = Path(__file__).parent.parent / "tasks"
        
        self.tasks_dir = tasks_dir
        self.tasks_dir.mkdir(exist_ok=True)
    
    def load_task(self, task_id: str) -> Dict[str, Any]:
        """
        Load a task definition from JSON.
        
        Args:
            task_id: Task identifier (e.g., "banking_reserve_001")
        
        Returns:
            Task definition dictionary
        """
        task_file = self.tasks_dir / task_id / "task.json"
        if not task_file.exists():
            raise FileNotFoundError(f"Task not found: {task_id}")
        
        with open(task_file) as f:
            task_def = json.load(f)
        
        logger.info(f"Loaded task: {task_id}")
        return task_def
    
    def list_tasks(self) -> list[str]:
        """
        List all available tasks.
        
        Returns:
            List of task IDs
        """
        tasks = []
        if not self.tasks_dir.exists():
            return tasks
        
        for task_dir in self.tasks_dir.iterdir():
            if task_dir.is_dir() and (task_dir / "task.json").exists():
                tasks.append(task_dir.name)
        
        return sorted(tasks)
    
    def get_task_dir(self, task_id: str) -> Path:
        """Get the directory for a task."""
        return self.tasks_dir / task_id
    
    def get_initial_files(self, task_id: str) -> Dict[str, Path]:
        """
        Get initial files for a task.
        
        Returns:
            Dict mapping filenames to host paths
        """
        task_dir = self.get_task_dir(task_id)
        initial_dir = task_dir / "initial"
        
        if not initial_dir.exists():
            return {}
        
        files = {}
        for file_path in initial_dir.iterdir():
            if file_path.is_file():
                files[file_path.name] = file_path
        
        return files
    
    def get_oracle_files(self, task_id: str) -> Dict[str, Path]:
        """
        Get oracle (expected output) files for a task.
        
        Returns:
            Dict mapping filenames to host paths
        """
        task_dir = self.get_task_dir(task_id)
        oracle_dir = task_dir / "oracle"
        
        if not oracle_dir.exists():
            return {}
        
        files = {}
        for file_path in oracle_dir.iterdir():
            if file_path.is_file():
                files[file_path.name] = file_path
        
        return files
    
    def create_task(
        self,
        task_id: str,
        title: str,
        description: str,
        initial_files: Dict[str, Path],
        oracle_files: Dict[str, Path],
        time_limit: int = 600
    ) -> Path:
        """
        Create a new task definition.
        
        Args:
            task_id: Unique task identifier
            title: Human-readable title
            description: Task instructions for the agent
            initial_files: Dict mapping filenames to source paths
            oracle_files: Dict mapping filenames to oracle paths
            time_limit: Time limit in seconds
        
        Returns:
            Path to created task directory
        """
        task_dir = self.tasks_dir / task_id
        task_dir.mkdir(exist_ok=True)
        
        # Create subdirectories
        initial_dir = task_dir / "initial"
        oracle_dir = task_dir / "oracle"
        initial_dir.mkdir(exist_ok=True)
        oracle_dir.mkdir(exist_ok=True)
        
        # Copy initial files
        import shutil
        for filename, src_path in initial_files.items():
            dest = initial_dir / filename
            shutil.copy2(src_path, dest)
            logger.info(f"Copied initial file: {filename}")
        
        # Copy oracle files
        for filename, src_path in oracle_files.items():
            dest = oracle_dir / filename
            shutil.copy2(src_path, dest)
            logger.info(f"Copied oracle file: {filename}")
        
        # Create task.json
        task_def = {
            "task_id": task_id,
            "title": title,
            "description": description,
            "time_limit_seconds": time_limit,
            "initial_files": list(initial_files.keys()),
            "expected_outputs": list(oracle_files.keys())
        }
        
        task_json = task_dir / "task.json"
        with open(task_json, 'w') as f:
            json.dump(task_def, f, indent=2)
        
        logger.info(f"Created task: {task_id} at {task_dir}")
        return task_dir
