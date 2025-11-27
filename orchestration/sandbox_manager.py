"""Docker container lifecycle management."""
import docker
from docker.models.containers import Container
from docker.errors import DockerException, ImageNotFound, APIError
import logging
from pathlib import Path
from typing import Optional, Dict, Any
import threading
import time

logger = logging.getLogger(__name__)


class SandboxManager:
    """Manages Docker containers for task execution."""
    
    def __init__(
        self, 
        image_name: str = "libreoffice-sandbox:latest",
        workspace_path: Optional[Path] = None
    ):
        self.image_name = image_name
        self.workspace_path = workspace_path or Path.cwd() / "workspace"
        self.workspace_path.mkdir(exist_ok=True)
        
        try:
            self.client = docker.from_env()
            logger.info(f"Connected to Docker daemon")
        except DockerException as e:
            logger.error(f"Failed to connect to Docker: {e}")
            logger.error("Make sure Docker Desktop is running!")
            logger.error("Run 'docker version' to check Docker status")
            raise RuntimeError(
                "Cannot connect to Docker daemon. "
                "Please start Docker Desktop and try again."
            ) from e
        
        self.container: Optional[Container] = None
        self.container_id: Optional[str] = None
        self.timeout_timer: Optional[threading.Timer] = None
        self.timed_out: bool = False
    
    def build_image(self, dockerfile_path: Path) -> None:
        """Build Docker image from Dockerfile."""
        logger.info(f"Building Docker image '{self.image_name}' from {dockerfile_path}")
        try:
            image, build_logs = self.client.images.build(
                path=str(dockerfile_path),
                tag=self.image_name,
                rm=True,  # Remove intermediate containers
                forcerm=True
            )
            
            # Print build logs
            for log in build_logs:
                if 'stream' in log:
                    print(log['stream'].strip())
            
            logger.info(f"Successfully built image: {image.tags}")
        except DockerException as e:
            logger.error(f"Failed to build image: {e}")
            raise
    
    def start_container(
        self, 
        memory_limit: str = "2g",
        cpu_quota: int = 100000,
        network_mode: str = "none",
        use_volume_mount: bool = False,
        user: str | None = None,
        timeout_seconds: int | None = None
    ) -> str:
        """Start container with resource limits and optional timeout."""
        if self.container is not None:
            logger.warning("Container already running, stopping it first")
            self.stop_container()
        
        try:
            # Check if image exists
            try:
                self.client.images.get(self.image_name)
            except ImageNotFound:
                logger.error(f"Image '{self.image_name}' not found. Build it first with build_image()")
                raise
            
            logger.info(f"Starting container from image '{self.image_name}'")
            
            # Prepare container config
            container_config = {
                'image': self.image_name,
                'detach': True,
                'remove': False,  # Don't auto-remove so we can extract files
                'mem_limit': memory_limit,
                'cpu_quota': cpu_quota,
                'network_mode': network_mode,
                'working_dir': '/workspace'
            }
            
            # Set user if specified
            if user is not None:
                container_config['user'] = user
                logger.info(f"Running container as user: {user}")
            
            # Add volume mount only if requested (for development/testing)
            # For RL tasks, use filesystem snapshot from task image instead
            if use_volume_mount:
                container_config['volumes'] = {
                    str(self.workspace_path.absolute()): {
                        'bind': '/workspace',
                        'mode': 'rw'
                    }
                }
                logger.info("Using volume mount for workspace (development mode)")
            else:
                logger.info("Using task image filesystem snapshot (RL mode)")
            
            self.container = self.client.containers.run(**container_config)
            
            self.container_id = self.container.id
            logger.info(f"Container started: {self.container_id[:12]}")
            
            # Set up timeout if specified
            if timeout_seconds is not None and timeout_seconds > 0:
                def timeout_handler():
                    self.timed_out = True
                    if self.container is not None:
                        logger.warning(f"Container timeout ({timeout_seconds}s) - killing container")
                        try:
                            self.container.kill()
                        except Exception as e:
                            logger.error(f"Failed to kill container: {e}")
                
                self.timeout_timer = threading.Timer(timeout_seconds, timeout_handler)
                self.timeout_timer.daemon = True
                self.timeout_timer.start()
                logger.info(f"Timeout set: {timeout_seconds} seconds")
            
            return self.container_id
            
        except DockerException as e:
            logger.error(f"Failed to start container: {e}")
            raise
    
    def execute_command(
        self, 
        command: str | list[str],
        workdir: Optional[str] = None
    ) -> Dict[str, Any]:
        """Execute command in container, returns exit_code/output/error."""
        if self.container is None:
            raise RuntimeError("No container running. Call start_container() first.")
        
        try:
            logger.debug(f"Executing command: {command}")
            exec_result = self.container.exec_run(
                command,
                workdir=workdir or "/workspace",
                demux=True  # Separate stdout and stderr
            )
            
            exit_code = exec_result.exit_code
            stdout, stderr = exec_result.output
            
            # Decode bytes to strings
            stdout_str = stdout.decode('utf-8') if stdout else ""
            stderr_str = stderr.decode('utf-8') if stderr else ""
            
            result = {
                'exit_code': exit_code,
                'output': stdout_str,
                'error': stderr_str
            }
            
            if exit_code == 0:
                logger.debug(f"Command succeeded: {stdout_str[:100]}")
            else:
                logger.warning(f"Command failed (exit {exit_code}): {stderr_str}")
            
            return result
            
        except APIError as e:
            logger.error(f"Failed to execute command: {e}")
            raise
    
    def stop_container(self, timeout: int = 10) -> None:
        """
        Stop and remove the container.
        
        Args:
            timeout: Seconds to wait before killing container
        """
        # Cancel timeout timer if active
        if self.timeout_timer is not None:
            self.timeout_timer.cancel()
            self.timeout_timer = None
        
        if self.container is None:
            logger.debug("No container to stop")
            return
        
        try:
            logger.info(f"Stopping container {self.container_id[:12]}")
            self.container.stop(timeout=timeout)
            self.container.remove()
            if self.timed_out:
                logger.warning("Container was killed due to timeout")
            else:
                logger.info("Container stopped and removed")
        except DockerException as e:
            logger.warning(f"Error stopping container: {e}")
        finally:
            self.container = None
            self.container_id = None
            self.timed_out = False
    
    def is_running(self) -> bool:
        """Check if container is currently running."""
        if self.container is None:
            return False
        
        try:
            self.container.reload()
            return self.container.status == "running"
        except DockerException:
            return False
    
    def reconnect_to_container(self, container_id: str) -> None:
        """
        Reconnect to an existing container.
        
        This is used when MCP server runs as subprocess and needs to
        connect to the container started by the parent process.
        
        Args:
            container_id: Docker container ID to reconnect to
        """
        try:
            self.container = self.client.containers.get(container_id)
            self.container_id = container_id
            
            # Verify it's running
            if self.container.status != "running":
                logger.warning(f"Container {container_id[:12]} is not running (status: {self.container.status})")
            else:
                logger.info(f"Reconnected to container: {container_id[:12]}")
        
        except DockerException as e:
            logger.error(f"Failed to reconnect to container {container_id}: {e}")
            raise RuntimeError(f"Could not reconnect to container {container_id}") from e
    
    def start_gui(self, filename: str | None = None) -> None:
        """Start VNC server virtual display and open file in LibreOffice GUI."""
        if self.container is None:
            raise RuntimeError("No container running")
        
        logger.info("Starting GUI mode (Xvfb + LibreOffice)")
        
        # Back to Xvfb - my manual test with test_edit.png WORKED with Xvfb!
        result = self.execute_command([
            "sh", "-c", 
            "Xvfb :99 -screen 0 1024x768x24 +extension XTEST -ac > /tmp/xvfb.log 2>&1 &"
        ])
        
        if result['exit_code'] != 0:
            logger.error(f"Failed to start Xvfb: {result['error']}")
            raise RuntimeError("Could not start virtual display")
        
        # Wait for display to be ready
        time.sleep(2)
        logger.info("Xvfb started on :99")
        
        # Start window manager (helps with focus/input)
        result = self.execute_command([
            "sh", "-c",
            "DISPLAY=:99 openbox > /tmp/openbox.log 2>&1 &"
        ])
        time.sleep(1)
        logger.info("Openbox window manager started")
        
        # Open file in LibreOffice if specified
        if filename:
            # Disable first-run tips/dialogs
            result = self.execute_command([
                "sh", "-c",
                f"DISPLAY=:99 libreoffice --calc --nofirststartwizard --nologo /workspace/{filename} > /tmp/libreoffice.log 2>&1 &"
            ])
            
            if result['exit_code'] != 0:
                logger.warning(f"LibreOffice might not have started: {result['error']}")
            
            # Wait for LibreOffice to open
            time.sleep(4)
            logger.info(f"LibreOffice opened with {filename}")
            
            # LibreOffice Calc starts with cursor at A1 by default
            logger.info("Spreadsheet ready, cursor at A1")
        else:
            logger.info("Xvfb ready (no file opened)")
    
    def get_container_logs(self) -> str:
        """Get container logs."""
        if self.container is None:
            return ""
        
        try:
            return self.container.logs().decode('utf-8')
        except DockerException as e:
            logger.error(f"Failed to get logs: {e}")
            return ""
    
    def copy_files_to_container(self, files: Dict[str, Path]) -> None:
        """Copy files from host to container using tar archives."""
        if self.container is None:
            raise RuntimeError("No container running. Call start_container() first.")
        
        import tarfile
        import io
        
        for container_path, host_path in files.items():
            if not host_path.exists():
                raise FileNotFoundError(f"Host file not found: {host_path}")
            
            logger.info(f"Copying {host_path} -> container:{container_path}")
            
            # Create tar archive in memory
            tar_stream = io.BytesIO()
            with tarfile.open(fileobj=tar_stream, mode='w') as tar:
                tar.add(str(host_path), arcname=Path(container_path).name)
            tar_stream.seek(0)
            
            # Extract to container
            container_dir = str(Path(container_path).parent)
            self.container.put_archive(container_dir, tar_stream.read())
            
            logger.debug(f"Successfully copied to {container_path}")
    
    def extract_files_from_container(self, file_paths: list[str]) -> Dict[str, bytes]:
        """Extract files from container, returns dict of path -> bytes."""
        if self.container is None:
            raise RuntimeError("No container running. Call start_container() first.")
        
        import tarfile
        import io
        
        extracted = {}
        
        for file_path in file_paths:
            logger.info(f"Extracting container:{file_path}")
            
            try:
                # Get file as tar archive
                bits, stat = self.container.get_archive(file_path)
                
                # Extract from tar
                tar_stream = io.BytesIO()
                for chunk in bits:
                    tar_stream.write(chunk)
                tar_stream.seek(0)
                
                with tarfile.open(fileobj=tar_stream, mode='r') as tar:
                    file_name = Path(file_path).name
                    member = tar.getmember(file_name)
                    file_obj = tar.extractfile(member)
                    if file_obj:
                        extracted[file_path] = file_obj.read()
                        logger.debug(f"Extracted {len(extracted[file_path])} bytes")
                    else:
                        raise RuntimeError(f"Could not extract file: {file_path}")
                        
            except Exception as e:
                logger.error(f"Failed to extract {file_path}: {e}")
                raise RuntimeError(f"Could not extract {file_path} from container") from e
        
        return extracted
    
    def cleanup(self) -> None:
        """Clean up resources."""
        self.stop_container()
        logger.info("Sandbox manager cleaned up")
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.cleanup()

