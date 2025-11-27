"""MCP server providing tools for spreadsheet and database tasks."""
from typing import Any
from pathlib import Path
from mcp.server.fastmcp import FastMCP
from orchestration.sandbox_manager import SandboxManager
from orchestration.task_manager import TaskManager

# Initialize FastMCP server
mcp = FastMCP("libreoffice-sandbox")

# Global state (for when MCP server is used with start_episode.py)
sandbox_manager: SandboxManager | None = None
task_manager: TaskManager | None = None
current_task_id: str | None = None
current_run_dir: Path | None = None


def load_episode_context():
    """Load episode context if it exists."""
    global current_task_id, current_run_dir, sandbox_manager
    
    context_file = Path(__file__).parent / ".episode_context.json"
    if context_file.exists():
        import json
        with open(context_file) as f:
            context = json.load(f)
        
        if context.get("task_id"):
            current_task_id = context["task_id"]
        if context.get("run_dir"):
            current_run_dir = Path(context["run_dir"])
            
            # Use the run dir as workspace
            if sandbox_manager is None:
                sandbox_manager = SandboxManager(workspace_path=current_run_dir)


def ensure_sandbox() -> SandboxManager:
    """Ensure sandbox is running, start if needed."""
    global sandbox_manager
    
    # Check if episode context exists
    load_episode_context()
    
    if sandbox_manager is None or not sandbox_manager.is_running():
        if sandbox_manager is None:
            sandbox_manager = SandboxManager()
        
        sandbox_dir = Path(__file__).parent / "sandbox"
        
        # Build image if needed
        try:
            sandbox_manager.client.images.get(sandbox_manager.image_name)
        except Exception:
            sandbox_manager.build_image(sandbox_dir)
        
        # Start container (with volume mount for Claude Desktop testing)
        sandbox_manager.start_container(use_volume_mount=True)
    
    return sandbox_manager


def execute_python_in_sandbox(code: str) -> dict[str, Any]:
    """
    Execute Python code inside the sandbox container.
    
    Args:
        code: Python code to execute
    
    Returns:
        Dict with 'exit_code', 'output', 'error'
    """
    manager = ensure_sandbox()
    return manager.execute_command(["python", "-c", code])


@mcp.tool()
def read_cell(filename: str, sheet: str, cell: str) -> str:
    """Read value from a cell (e.g., read_cell("data.ods", "Sheet1", "A1"))."""
    # Convert A1 notation to row/col indices
    col_letter = ''.join(c for c in cell if c.isalpha()).upper()
    row_num = int(''.join(c for c in cell if c.isdigit())) - 1  # 0-indexed
    
    # Convert column letter to index (A=0, B=1, Z=25, AA=26, etc.)
    col_num = 0
    for i, char in enumerate(reversed(col_letter)):
        col_num += (ord(char) - ord('A') + 1) * (26 ** i)
    col_num -= 1  # 0-indexed
    
    # Python code to read the cell
    python_code = f"""
from odf.opendocument import load
from odf import table, text

# Load spreadsheet
doc = load('/workspace/{filename}')

# Find the sheet
tables = doc.spreadsheet.getElementsByType(table.Table)
target_table = None
for tbl in tables:
    if tbl.getAttribute('name') == '{sheet}':
        target_table = tbl
        break

if target_table is None:
    print('ERROR: Sheet not found')
    exit(1)

# Get the row
rows = target_table.getElementsByType(table.TableRow)
if {row_num} >= len(rows):
    print('ERROR: Row index out of range')
    exit(1)

# Get the cell
cells = rows[{row_num}].getElementsByType(table.TableCell)
if {col_num} >= len(cells):
    print('ERROR: Column index out of range')
    exit(1)

# Extract text from cell
paragraphs = cells[{col_num}].getElementsByType(text.P)
if paragraphs:
    print(str(paragraphs[0]))
else:
    print('')
"""
    
    result = execute_python_in_sandbox(python_code)
    
    if result['exit_code'] != 0:
        error_msg = result['error'] or result['output']
        raise RuntimeError(f"Failed to read cell: {error_msg}")
    
    return result['output'].strip()


@mcp.tool()
def get_spreadsheet_info(filename: str) -> dict[str, Any]:
    """
    Get information about a spreadsheet file.
    
    Args:
        filename: Name of the file in /workspace (e.g., "data.ods")
    
    Returns:
        Dictionary with sheet names and dimensions
    
    Example:
        get_spreadsheet_info("data.ods") -> 
        {
            "sheets": [
                {"name": "Sheet1", "rows": 100, "cols": 10},
                {"name": "Sheet2", "rows": 50, "cols": 5}
            ]
        }
    """
    python_code = f"""
import json
from odf.opendocument import load
from odf import table

# Load spreadsheet
doc = load('/workspace/{filename}')

# Get all sheets
tables = doc.spreadsheet.getElementsByType(table.Table)

sheets = []
for tbl in tables:
    name = tbl.getAttribute('name')
    rows = tbl.getElementsByType(table.TableRow)
    
    # Count max columns
    max_cols = 0
    for row in rows:
        cells = row.getElementsByType(table.TableCell)
        max_cols = max(max_cols, len(cells))
    
    sheets.append({{
        'name': name,
        'rows': len(rows),
        'cols': max_cols
    }})

print(json.dumps({{'sheets': sheets}}))
"""
    
    result = execute_python_in_sandbox(python_code)
    
    if result['exit_code'] != 0:
        error_msg = result['error'] or result['output']
        raise RuntimeError(f"Failed to get spreadsheet info: {error_msg}")
    
    import json
    return json.loads(result['output'].strip())


@mcp.tool()
def list_workspace_files() -> list[str]:
    """
    List all files in the workspace directory.
    
    Returns:
        List of filenames in /workspace
    
    Example:
        list_workspace_files() -> ["sales.ods", "template.ods"]
    """
    manager = ensure_sandbox()
    result = manager.execute_command(["ls", "-1", "/workspace"])
    
    if result['exit_code'] != 0:
        raise RuntimeError(f"Failed to list files: {result['error']}")
    
    files = [f.strip() for f in result['output'].split('\n') if f.strip()]
    return files


# Cleanup handler
@mcp.tool()
def write_cell(filename: str, sheet: str, cell: str, value: str) -> str:
    """Write value to a cell."""
    # Convert A1 notation to row/col indices
    col_letter = ''.join(c for c in cell if c.isalpha()).upper()
    row_num = int(''.join(c for c in cell if c.isdigit())) - 1  # 0-indexed
    
    # Convert column letter to index
    col_num = 0
    for i, char in enumerate(reversed(col_letter)):
        col_num += (ord(char) - ord('A') + 1) * (26 ** i)
    col_num -= 1  # 0-indexed
    
    # Python code to write the cell
    python_code = f"""
from odf.opendocument import load
from odf import table
from odf.table import TableRow, TableCell
from odf.text import P

# Load or create spreadsheet
try:
    doc = load('/workspace/{filename}')
except FileNotFoundError:
    from odf.opendocument import OpenDocumentSpreadsheet
    from odf.table import Table
    doc = OpenDocumentSpreadsheet()
    # Create the sheet if it doesn't exist
    new_table = Table(name='{sheet}')
    doc.spreadsheet.addElement(new_table)

# Find the sheet
tables = doc.spreadsheet.getElementsByType(table.Table)
target_table = None
for tbl in tables:
    if tbl.getAttribute('name') == '{sheet}':
        target_table = tbl
        break

if target_table is None:
    print('ERROR: Sheet not found')
    exit(1)

# Get or create rows up to target row
rows = target_table.getElementsByType(table.TableRow)
while len(rows) <= {row_num}:
    target_table.addElement(TableRow())
    rows = target_table.getElementsByType(table.TableRow)

# Get or create cells up to target column
target_row = rows[{row_num}]
cells = target_row.getElementsByType(table.TableCell)
while len(cells) <= {col_num}:
    target_row.addElement(TableCell())
    cells = target_row.getElementsByType(table.TableCell)

# Write to the cell
target_cell = cells[{col_num}]

# Clear existing content
for child in list(target_cell.childNodes):
    target_cell.removeChild(child)

# Add new content
target_cell.addElement(P(text='{value}'))

# Save
doc.save('/workspace/{filename}')
print('Success')
"""
    
    result = execute_python_in_sandbox(python_code)
    
    if result['exit_code'] != 0:
        error_msg = result['error'] or result['output']
        raise RuntimeError(f"Failed to write cell: {error_msg}")
    
    return f"Successfully wrote '{value}' to {sheet}!{cell}"


@mcp.tool()
def write_formula(filename: str, sheet: str, cell: str, formula: str) -> str:
    """Write formula to a cell (e.g., "=SUM(A1:A10)")."""
    # Convert A1 notation to row/col indices
    col_letter = ''.join(c for c in cell if c.isalpha()).upper()
    row_num = int(''.join(c for c in cell if c.isdigit())) - 1  # 0-indexed
    
    # Convert column letter to index
    col_num = 0
    for i, char in enumerate(reversed(col_letter)):
        col_num += (ord(char) - ord('A') + 1) * (26 ** i)
    col_num -= 1  # 0-indexed
    
    # Escape formula for Python string
    formula_escaped = formula.replace("'", "\\'")
    
    # Python code to write formula
    python_code = f"""
from odf.opendocument import load
from odf import table
from odf.table import TableRow, TableCell
from odf.text import P

# Load spreadsheet
doc = load('/workspace/{filename}')

# Find the sheet
tables = doc.spreadsheet.getElementsByType(table.Table)
target_table = None
for tbl in tables:
    if tbl.getAttribute('name') == '{sheet}':
        target_table = tbl
        break

if target_table is None:
    print('ERROR: Sheet not found')
    exit(1)

# Get or create rows up to target row
rows = target_table.getElementsByType(table.TableRow)
while len(rows) <= {row_num}:
    target_table.addElement(TableRow())
    rows = target_table.getElementsByType(table.TableRow)

# Get or create cells up to target column
target_row = rows[{row_num}]
cells = target_row.getElementsByType(table.TableCell)
while len(cells) <= {col_num}:
    target_row.addElement(TableCell())
    cells = target_row.getElementsByType(table.TableCell)

# Write formula to the cell
target_cell = cells[{col_num}]

# Set formula attribute
target_cell.setAttribute('formula', '{formula_escaped}')

# Save
doc.save('/workspace/{filename}')
print('Success')
"""
    
    result = execute_python_in_sandbox(python_code)
    
    if result['exit_code'] != 0:
        error_msg = result['error'] or result['output']
        raise RuntimeError(f"Failed to write formula: {error_msg}")
    
    return f"Successfully wrote formula '{formula}' to {sheet}!{cell}"


@mcp.tool()
def get_task_description() -> dict[str, Any]:
    """
    Get the description of the current task.
    
    Returns:
        Task definition including description, time limit, etc.
    
    Example:
        get_task_description() -> {
            "task_id": "banking_001",
            "title": "Calculate Banking Reserves",
            "description": "Using the provided spreadsheet, calculate reserves...",
            "time_limit_seconds": 600
        }
    """
    global task_manager, current_task_id
    
    if current_task_id is None:
        return {
            "error": "No task loaded",
            "message": "This is a development environment. In RL mode, tasks are loaded automatically."
        }
    
    if task_manager is None:
        task_manager = TaskManager()
    
    try:
        task_def = task_manager.load_task(current_task_id)
        return {
            "task_id": task_def.get("task_id"),
            "title": task_def.get("title"),
            "description": task_def.get("description"),
            "time_limit_seconds": task_def.get("time_limit_seconds"),
            "starting_files": list(task_def.get("starting_files", {}).keys())
        }
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def submit_task(output_files: list[str] | None = None) -> dict[str, Any]:
    """
    Submit task outputs for grading.
    
    Args:
        output_files: List of filenames in /workspace to grade (e.g., ["sales.ods"])
                     If None, grades all files in workspace
    
    Returns:
        Grading results with score and feedback
    
    Example:
        submit_task(["sales.ods"]) -> {
            "passed": True,
            "score": 1.0,
            "feedback": "Perfect! All cells correct."
        }
    """
    global sandbox_manager, task_manager, current_task_id, current_run_dir
    
    if current_task_id is None:
        return {
            "error": "No task loaded",
            "message": "Use start_episode.py to start a task episode"
        }
    
    if sandbox_manager is None or not sandbox_manager.is_running():
        return {"error": "No sandbox running"}
    
    if task_manager is None:
        task_manager = TaskManager()
    
    try:
        # If using run dir (episode mode), grade from there
        if current_run_dir and current_run_dir.exists():
            from evaluation.grader import grade_task_run
            result = grade_task_run(current_task_id, current_run_dir)
            return result
        
        # Otherwise extract from container (legacy mode)
        if output_files is None:
            output_files = list_workspace_files()
        
        # Convert to full paths
        full_paths = [f"/workspace/{f}" if not f.startswith("/") else f 
                     for f in output_files]
        
        extracted = sandbox_manager.extract_files_from_container(full_paths)
        
        # Grade (old method - not ideal but works)
        return {
            "error": "Cannot grade without run directory context",
            "message": "Use start_episode.py for proper grading workflow"
        }
        
    except Exception as e:
        return {
            "error": str(e),
            "passed": False,
            "score": 0.0
        }


@mcp.tool()
def execute_sql(database: str, query: str) -> dict[str, Any]:
    """Execute SQL query on SQLite database (SELECT only)."""
    # Safety: Only allow SELECT queries
    if not query.strip().upper().startswith("SELECT"):
        raise ValueError("Only SELECT queries are allowed")
    
    python_code = f"""
import sqlite3
import json

conn = sqlite3.connect('/workspace/{database}')
cursor = conn.cursor()

try:
    cursor.execute('''{query}''')
    columns = [desc[0] for desc in cursor.description]
    rows = cursor.fetchall()
    
    result = {{
        'columns': columns,
        'rows': rows
    }}
    
    print(json.dumps(result))
finally:
    conn.close()
"""
    
    result = execute_python_in_sandbox(python_code)
    
    if result['exit_code'] != 0:
        error_msg = result['error'] or result['output']
        raise RuntimeError(f"SQL query failed: {error_msg}")
    
    import json
    return json.loads(result['output'].strip())


@mcp.tool()
def list_database_tables(database: str) -> list[str]:
    """
    List all tables in a SQLite database.
    
    Args:
        database: Database filename in /workspace (e.g., "sales.db")
    
    Returns:
        List of table names
    
    Example:
        list_database_tables("sales.db") -> ["products", "customers", "orders"]
    """
    python_code = f"""
import sqlite3
import json

conn = sqlite3.connect('/workspace/{database}')
cursor = conn.cursor()

try:
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [row[0] for row in cursor.fetchall()]
    print(json.dumps(tables))
finally:
    conn.close()
"""
    
    result = execute_python_in_sandbox(python_code)
    
    if result['exit_code'] != 0:
        error_msg = result['error'] or result['output']
        raise RuntimeError(f"Failed to list tables: {error_msg}")
    
    import json
    return json.loads(result['output'].strip())


@mcp.tool()
def create_new_spreadsheet(filename: str, sheet_name: str = "Sheet1") -> str:
    """
    Create a new empty spreadsheet file.
    
    Args:
        filename: Name for the new file (e.g., "report.ods")
        sheet_name: Name for the first sheet
    
    Returns:
        Success message
    
    Example:
        create_new_spreadsheet("report.ods", "Summary") -> "Created report.ods"
    """
    python_code = f"""
from odf.opendocument import OpenDocumentSpreadsheet
from odf.table import Table

doc = OpenDocumentSpreadsheet()
table = Table(name='{sheet_name}')
doc.spreadsheet.addElement(table)
doc.save('/workspace/{filename}')
print('Success')
"""
    
    result = execute_python_in_sandbox(python_code)
    
    if result['exit_code'] != 0:
        error_msg = result['error'] or result['output']
        raise RuntimeError(f"Failed to create spreadsheet: {error_msg}")
    
    return f"Created {filename} with sheet '{sheet_name}'"


@mcp.tool()
def take_screenshot() -> str:
    """Capture screenshot, returns base64 PNG."""
    global sandbox_manager
    
    if sandbox_manager is None or not sandbox_manager.is_running():
        return "Error: No sandbox running"
    
    python_code = """
import subprocess
import base64

# Take screenshot using scrot
subprocess.run(['scrot', '/tmp/screenshot.png'], env={'DISPLAY': ':99'})

# Read and encode
with open('/tmp/screenshot.png', 'rb') as f:
    img_data = f.read()
    b64 = base64.b64encode(img_data).decode('utf-8')
    print(b64)
"""
    
    result = execute_python_in_sandbox(python_code)
    
    if result['exit_code'] != 0:
        error_msg = result['error'] or result['output']
        raise RuntimeError(f"Screenshot failed: {error_msg}")
    
    return result['output'].strip()


@mcp.tool()
def click(x: int, y: int) -> str:
    """Click mouse at coordinates."""
    global sandbox_manager
    
    if sandbox_manager is None or not sandbox_manager.is_running():
        return "Error: No sandbox running"
    
    result = sandbox_manager.execute_command([
        "sh", "-c",
        f"DISPLAY=:99 xdotool mousemove {x} {y} click 1"
    ])
    
    if result['exit_code'] != 0:
        raise RuntimeError(f"Click failed: {result['error']}")
    
    return f"Clicked at ({x}, {y})"


@mcp.tool()
def double_click(x: int, y: int) -> str:
    """Double-click mouse at coordinates."""
    global sandbox_manager
    
    if sandbox_manager is None or not sandbox_manager.is_running():
        return "Error: No sandbox running"
    
    # Use xdotool to double-click
    result = sandbox_manager.execute_command([
        "sh", "-c",
        f"DISPLAY=:99 xdotool mousemove {x} {y} click --repeat 2 --delay 100 1"
    ])
    
    if result['exit_code'] != 0:
        raise RuntimeError(f"Double-click failed: {result['error']}")
    
    return f"Double-clicked at ({x}, {y})"


@mcp.tool()
def type_text(text: str) -> str:
    """
    Type text at the current cursor position (for computer use mode).
    
    Args:
        text: Text to type
    
    Returns:
        Success message
    
    Example:
        type_text("Hello World") -> "Typed: Hello World"
    """
    global sandbox_manager
    
    if sandbox_manager is None or not sandbox_manager.is_running():
        return "Error: No sandbox running"
    
    # Escape text for shell
    escaped_text = text.replace("'", "'\\''")
    
    result = sandbox_manager.execute_command([
        "sh", "-c",
        f"DISPLAY=:99 xdotool type '{escaped_text}'"
    ])
    
    if result['exit_code'] != 0:
        raise RuntimeError(f"Type failed: {result['error']}")
    
    return f"Typed: {text}"


@mcp.tool()
def press_key(key: str) -> str:
    """
    Press a keyboard key or key combination (for computer use mode).
    
    Args:
        key: Key to press (e.g., "Return", "ctrl+s", "Tab")
    
    Returns:
        Success message
    
    Example:
        press_key("ctrl+s") -> "Pressed: ctrl+s"
        press_key("Return") -> "Pressed: Return"
    """
    global sandbox_manager
    
    if sandbox_manager is None or not sandbox_manager.is_running():
        return "Error: No sandbox running"
    
    result = sandbox_manager.execute_command([
        "sh", "-c",
        f"DISPLAY=:99 xdotool key {key}"
    ])
    
    if result['exit_code'] != 0:
        raise RuntimeError(f"Key press failed: {result['error']}")
    
    return f"Pressed: {key}"


@mcp.tool()
def reset_environment() -> str:
    """
    Reset the sandbox environment (stop and remove container).
    Useful for starting fresh on a new task.
    
    Returns:
        Status message
    """
    global sandbox_manager
    
    if sandbox_manager is not None:
        sandbox_manager.cleanup()
        sandbox_manager = None
        return "Environment reset successfully"
    
    return "Environment was not running"


def get_tool_use_tools() -> dict:
    """Get all tool-use mode MCP tools."""
    return {
        "read_cell": read_cell,
        "write_cell": write_cell,
        "write_formula": write_formula,
        "get_spreadsheet_info": get_spreadsheet_info,
        "list_workspace_files": list_workspace_files,
        "execute_sql": execute_sql,
        "list_database_tables": list_database_tables,
        "create_new_spreadsheet": create_new_spreadsheet,
        "submit_task": submit_task
    }


def get_computer_use_tools() -> dict:
    """Get all computer-use mode MCP tools."""
    return {
        "take_screenshot": take_screenshot,
        "click": click,
        "double_click": double_click,
        "type_text": type_text,
        "press_key": press_key,
        "list_workspace_files": list_workspace_files,
        "submit_task": submit_task
    }


if __name__ == "__main__":
    # Run the MCP server
    mcp.run()
