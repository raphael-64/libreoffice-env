"""Episode orchestration - manages lifecycle from setup to grading."""
import logging
import shutil
from pathlib import Path
from typing import Dict, Any
from datetime import datetime

from orchestration.task_manager import TaskManager
from orchestration.sandbox_manager import SandboxManager
from grader import grade_task_run

logger = logging.getLogger(__name__)


class EpisodeRunner:
    """Manages individual task episodes."""
    
    def __init__(
        self,
        base_image: str = "libreoffice-sandbox:latest",
        runs_dir: Path | None = None
    ):
        """
        Initialize episode runner.
        
        Args:
            base_image: Base Docker image (built once, used forever)
            runs_dir: Directory to store episode runs
        """
        self.base_image = base_image
        
        if runs_dir is None:
            runs_dir = Path(__file__).parent.parent / "runs"
        
        self.runs_dir = runs_dir
        self.runs_dir.mkdir(exist_ok=True)
        
        self.task_manager = TaskManager()
        self.current_sandbox: SandboxManager | None = None
        self.current_run_dir: Path | None = None
    
    def setup_episode(self, task_id: str) -> Path:
        """
        Set up a new episode: create run directory and copy initial files.
        
        Args:
            task_id: Task identifier
        
        Returns:
            Path to run directory
        """
        # Load task definition
        task_def = self.task_manager.load_task(task_id)
        
        # Auto-generate episode number
        task_runs = self.runs_dir / task_id
        task_runs.mkdir(exist_ok=True)
        existing = [d for d in task_runs.iterdir() if d.is_dir()]
        episode_num = len(existing) + 1
        
        run_dir = self.runs_dir / task_id / f"run_{episode_num:03d}"
        run_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"Created run directory: {run_dir}")
        
        # Copy initial files from tasks/{task_id}/initial/ to run_dir/
        initial_files = self.task_manager.get_initial_files(task_id)
        for filename, src_path in initial_files.items():
            dest = run_dir / filename
            shutil.copy2(src_path, dest)
            logger.info(f"Copied {filename} to run directory")
        
        self.current_run_dir = run_dir
        return run_dir
    
    def start_episode(
        self,
        task_id: str,
        timeout_seconds: int | None = None
    ) -> tuple[SandboxManager, Path, Dict[str, Any]]:
        """
        Start a new episode.
        
        Args:
            task_id: Task identifier
            timeout_seconds: Timeout (uses task default if None)
        
        Returns:
            (SandboxManager, run_directory, task_definition)
        """
        # Setup episode
        run_dir = self.setup_episode(task_id)
        
        # Load task for timeout
        task_def = self.task_manager.load_task(task_id)
        if timeout_seconds is None:
            timeout_seconds = task_def.get("time_limit_seconds", 600)
        
        # Start container with run_dir mounted as /workspace
        logger.info(f"Starting container for episode (timeout: {timeout_seconds}s)")
        sandbox = SandboxManager(
            image_name=self.base_image,
            workspace_path=run_dir  # Mount THIS run dir
        )
        sandbox.start_container(
            use_volume_mount=True,  # Always mount run dir
            timeout_seconds=timeout_seconds
        )
        
        self.current_sandbox = sandbox
        
        logger.info(f"Episode started: {run_dir}")
        return sandbox, run_dir, task_def
    
    def end_episode(self, grade: bool = True, cleanup: bool = False) -> Dict[str, Any] | None:
        """
        End the current episode and optionally grade.
        
        Args:
            grade: Whether to grade the output
            cleanup: Whether to delete run directory after grading (for RL training)
        
        Returns:
            Grading result dict if grade=True, None otherwise
        """
        if self.current_sandbox is None:
            logger.warning("No active episode")
            return None
        
        result = None
        
        # Grade if requested
        if grade and self.current_run_dir is not None:
            logger.info("Grading episode...")
            # Extract task_id from run_dir path
            task_id = self.current_run_dir.parent.name
            result = grade_task_run(task_id, self.current_run_dir)
            
            logger.info(f"Grading complete: {result['passed']} (score: {result['score']})")
        
        # Cleanup sandbox
        self.current_sandbox.cleanup()
        self.current_sandbox = None
        
        # Optionally cleanup run directory (for RL training to save space)
        if cleanup and self.current_run_dir is not None:
            import shutil
            if self.current_run_dir.exists():
                shutil.rmtree(self.current_run_dir)
                logger.info(f"Cleaned up run directory: {self.current_run_dir}")
        
        return result
    
    def run_episode(
        self,
        task_id: str,
        agent_function
    ) -> Dict[str, Any]:
        """
        Run a complete episode with an agent function.
        
        Args:
            task_id: Task identifier
            agent_function: Function that takes (sandbox, task_def) and performs task
        
        Returns:
            Grading result
        """
        sandbox, run_dir, task_def = self.start_episode(task_id)
        
        try:
            # Agent acts
            logger.info("Agent acting...")
            agent_function(sandbox, task_def)
            
            # Grade
            result = self.end_episode(grade=True)
            return result
            
        except Exception as e:
            logger.error(f"Episode failed: {e}")
            self.end_episode(grade=False)
            raise

