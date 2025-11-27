"""MCP server providing tools for spreadsheet and database tasks."""
from typing import Any
from pathlib import Path
from mcp.server.fastmcp import FastMCP

from utils import get_context, CellRef

# Initialize FastMCP server
mcp = FastMCP("libreoffice-sandbox")


# ============================================================================
# Script Generation Helpers
# ============================================================================

def _read_cell_script(filename: str, sheet: str, row: int, col: int) -> str:
    """Generate Python script to read a cell."""
    return f"""
from odf.opendocument import load
from odf import table, text

doc = load('/workspace/{filename}')
tables = doc.spreadsheet.getElementsByType(table.Table)
target_table = None
for tbl in tables:
    if tbl.getAttribute('name') == '{sheet}':
        target_table = tbl
        break

if target_table is None:
    print('ERROR: Sheet not found')
    exit(1)

rows = target_table.getElementsByType(table.TableRow)
if {row} >= len(rows):
    print('ERROR: Row index out of range')
    exit(1)

cells = rows[{row}].getElementsByType(table.TableCell)
if {col} >= len(cells):
    print('ERROR: Column index out of range')
    exit(1)

paragraphs = cells[{col}].getElementsByType(text.P)
if paragraphs:
    print(str(paragraphs[0]))
else:
    print('')
"""


def _read_range_script(filename: str, sheet: str, start_row: int, start_col: int, 
                       end_row: int, end_col: int) -> str:
    """Generate Python script to read a range of cells."""
    return f"""
import json
from odf.opendocument import load
from odf import table, text

doc = load('/workspace/{filename}')
tables = doc.spreadsheet.getElementsByType(table.Table)
target_table = None
for tbl in tables:
    if tbl.getAttribute('name') == '{sheet}':
        target_table = tbl
        break

if target_table is None:
    print('ERROR: Sheet not found')
    exit(1)

rows = target_table.getElementsByType(table.TableRow)
if {end_row} >= len(rows):
    print('ERROR: End row index out of range')
    exit(1)

result = []
for row_idx in range({start_row}, {end_row} + 1):
    if row_idx >= len(rows):
        break
    
    row = rows[row_idx]
    cells = row.getElementsByType(table.TableCell)
    
    row_values = []
    for col_idx in range({start_col}, {end_col} + 1):
        if col_idx >= len(cells):
            row_values.append('')
        else:
            cell = cells[col_idx]
            paragraphs = cell.getElementsByType(text.P)
            if paragraphs:
                row_values.append(str(paragraphs[0]))
            else:
                row_values.append('')
    
    result.append(row_values)

print(json.dumps(result))
"""


def _write_cell_script(filename: str, sheet: str, row: int, col: int, value: str) -> str:
    """Generate Python script to write a cell value."""
    escaped_value = value.replace("'", "\\'")
    
    return f"""
from odf.opendocument import load
from odf import table
from odf.table import TableRow, TableCell
from odf.text import P

try:
    doc = load('/workspace/{filename}')
except FileNotFoundError:
    from odf.opendocument import OpenDocumentSpreadsheet
    from odf.table import Table
    doc = OpenDocumentSpreadsheet()
    new_table = Table(name='{sheet}')
    doc.spreadsheet.addElement(new_table)

tables = doc.spreadsheet.getElementsByType(table.Table)
target_table = None
for tbl in tables:
    if tbl.getAttribute('name') == '{sheet}':
        target_table = tbl
        break

if target_table is None:
    print('ERROR: Sheet not found')
    exit(1)

rows = target_table.getElementsByType(table.TableRow)
while len(rows) <= {row}:
    target_table.addElement(TableRow())
    rows = target_table.getElementsByType(table.TableRow)

target_row = rows[{row}]
cells = target_row.getElementsByType(table.TableCell)
while len(cells) <= {col}:
    target_row.addElement(TableCell())
    cells = target_row.getElementsByType(table.TableCell)

target_cell = cells[{col}]

for child in list(target_cell.childNodes):
    target_cell.removeChild(child)

target_cell.addElement(P(text='{escaped_value}'))

doc.save('/workspace/{filename}')
print('Success')
"""


def _write_formula_script(filename: str, sheet: str, row: int, col: int, formula: str) -> str:
    """Generate Python script to write a formula."""
    escaped_formula = formula.replace("'", "\\'")
    
    return f"""
from odf.opendocument import load
from odf import table
from odf.table import TableRow, TableCell

doc = load('/workspace/{filename}')

tables = doc.spreadsheet.getElementsByType(table.Table)
target_table = None
for tbl in tables:
    if tbl.getAttribute('name') == '{sheet}':
        target_table = tbl
        break

if target_table is None:
    print('ERROR: Sheet not found')
    exit(1)

rows = target_table.getElementsByType(table.TableRow)
while len(rows) <= {row}:
    target_table.addElement(TableRow())
    rows = target_table.getElementsByType(table.TableRow)

target_row = rows[{row}]
cells = target_row.getElementsByType(table.TableCell)
while len(cells) <= {col}:
    target_row.addElement(TableCell())
    cells = target_row.getElementsByType(table.TableCell)

target_cell = cells[{col}]
target_cell.setAttribute('formula', '{escaped_formula}')

doc.save('/workspace/{filename}')
print('Success')
"""


@mcp.tool()
def read_cell(filename: str, sheet: str, cell: str) -> str:
    """
    Read value from a single cell (e.g., read_cell("data.ods", "Sheet1", "A1")).
    
    For reading multiple cells, use read_range() instead.
    """
    ctx = get_context()
    
    # Validate it's a single cell, not a range
    if ':' in cell or '-' in cell:
        raise ValueError(
            f"read_cell only accepts single cells like 'A1'. "
            f"Got: '{cell}'. Use read_range() to read multiple cells."
        )
    
    cell_ref = CellRef.from_a1(cell)
    script = _read_cell_script(filename, sheet, cell_ref.row, cell_ref.col)
    result = ctx.sandbox_manager.execute_command(["python", "-c", script])
    
    if result['exit_code'] != 0:
        error_msg = result['error'] or result['output']
        raise RuntimeError(f"Failed to read cell: {error_msg}")
    
    return result['output'].strip()


@mcp.tool()
def read_range(filename: str, sheet: str, start_cell: str, end_cell: str) -> list[list[str]]:
    """
    Read a range of cells (e.g., read_range("data.ods", "Sheet1", "A1", "E1")).
    
    Returns a 2D array of cell values. For a single row like A1:E1, returns [[val1, val2, ...]].
    For multiple rows like A1:B3, returns [[a1, b1], [a2, b2], [a3, b3]].
    """
    ctx = get_context()
    
    start_ref = CellRef.from_a1(start_cell)
    end_ref = CellRef.from_a1(end_cell)
    script = _read_range_script(filename, sheet, start_ref.row, start_ref.col, end_ref.row, end_ref.col)
    result = ctx.sandbox_manager.execute_command(["python", "-c", script])
    
    if result['exit_code'] != 0:
        error_msg = result['error'] or result['output']
        raise RuntimeError(f"Failed to read range: {error_msg}")
    
    import json
    return json.loads(result['output'].strip())


@mcp.tool()
def write_cell(filename: str, sheet: str, cell: str, value: str) -> str:
    """Write value to a cell."""
    ctx = get_context()
    cell_ref = CellRef.from_a1(cell)
    script = _write_cell_script(filename, sheet, cell_ref.row, cell_ref.col, value)
    result = ctx.sandbox_manager.execute_command(["python", "-c", script])
    
    if result['exit_code'] != 0:
        error_msg = result['error'] or result['output']
        raise RuntimeError(f"Failed to write cell: {error_msg}")
    
    return f"Successfully wrote '{value}' to {sheet}!{cell}"


@mcp.tool()
def write_formula(filename: str, sheet: str, cell: str, formula: str) -> str:
    """Write formula to a cell (e.g., "=SUM(A1:A10)")."""
    ctx = get_context()
    cell_ref = CellRef.from_a1(cell)
    script = _write_formula_script(filename, sheet, cell_ref.row, cell_ref.col, formula)
    result = ctx.sandbox_manager.execute_command(["python", "-c", script])
    
    if result['exit_code'] != 0:
        error_msg = result['error'] or result['output']
        raise RuntimeError(f"Failed to write formula: {error_msg}")
    
    return f"Successfully wrote formula '{formula}' to {sheet}!{cell}"


@mcp.tool()
def get_spreadsheet_info(filename: str) -> dict[str, Any]:
    """
    Get information about a spreadsheet file.
    
    Args:
        filename: Name of the file in /workspace (e.g., "data.ods")
    
    Returns:
        Dictionary with sheet names and dimensions
    """
    ctx = get_context()
    
    python_code = f"""
import json
from odf.opendocument import load
from odf import table

doc = load('/workspace/{filename}')
tables = doc.spreadsheet.getElementsByType(table.Table)

sheets = []
for tbl in tables:
    name = tbl.getAttribute('name')
    rows = tbl.getElementsByType(table.TableRow)
    
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
    
    result = ctx.sandbox_manager.execute_command(["python", "-c", python_code])
    
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
    """
    ctx = get_context()
    result = ctx.sandbox_manager.execute_command(["ls", "-1", "/workspace"])
    
    if result['exit_code'] != 0:
        raise RuntimeError(f"Failed to list files: {result['error']}")
    
    files = [f.strip() for f in result['output'].split('\n') if f.strip()]
    return files


@mcp.tool()
def get_task_description() -> dict[str, Any]:
    """
    Get the description of the current task.
    
    Returns:
        Task definition including description, time limit, etc.
    """
    ctx = get_context()
    
    return {
        "task_id": ctx.task_id,
        "title": ctx.task_definition.get("title"),
        "description": ctx.task_definition.get("description"),
        "time_limit_seconds": ctx.task_definition.get("time_limit_seconds"),
        "starting_files": ctx.task_definition.get("initial_files", [])
    }


@mcp.tool()
def submit_task(output_files: list[str] | None = None) -> dict[str, Any]:
    """
    Submit task outputs for grading.
    
    Args:
        output_files: List of filenames in /workspace to grade (optional)
    
    Returns:
        Grading results with score and feedback
    """
    ctx = get_context()
    
    try:
        from grader import grade_task_run
        result = grade_task_run(ctx.task_id, ctx.run_dir)
        return result
        
    except Exception as e:
        return {
            "error": str(e),
            "passed": False,
            "score": 0.0
        }


@mcp.tool()
def execute_sql(database: str, query: str) -> dict[str, Any]:
    """Execute SQL query on SQLite database (SELECT only)."""
    ctx = get_context()
    
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
    
    result = ctx.sandbox_manager.execute_command(["python", "-c", python_code])
    
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
    """
    ctx = get_context()
    
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
    
    result = ctx.sandbox_manager.execute_command(["python", "-c", python_code])
    
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
    """
    ctx = get_context()
    
    python_code = f"""
from odf.opendocument import OpenDocumentSpreadsheet
from odf.table import Table

doc = OpenDocumentSpreadsheet()
table = Table(name='{sheet_name}')
doc.spreadsheet.addElement(table)
doc.save('/workspace/{filename}')
print('Success')
"""
    
    result = ctx.sandbox_manager.execute_command(["python", "-c", python_code])
    
    if result['exit_code'] != 0:
        error_msg = result['error'] or result['output']
        raise RuntimeError(f"Failed to create spreadsheet: {error_msg}")
    
    return f"Created {filename} with sheet '{sheet_name}'"


# ============================================================================
# Computer Use Mode Tools (GUI interaction)
# ============================================================================

@mcp.tool()
def take_screenshot() -> str:
    """Capture screenshot, returns base64 PNG."""
    ctx = get_context()
    
    import time
    import logging
    logger = logging.getLogger(__name__)
    
    # Generate unique screenshot name based on counter
    import os
    screenshot_dir = ctx.run_dir / "screenshots"
    screenshot_dir.mkdir(exist_ok=True)
    
    # Count existing screenshots to get next number
    existing = len([f for f in screenshot_dir.glob("*.png")])
    screenshot_name = f"screenshot_{existing:03d}.png"
    container_path = f"/workspace/screenshots/{screenshot_name}"
    
    # CRITICAL: Use DISPLAY=:99 inline for EVERY command
    # Docker exec_run doesn't preserve exported env vars between commands
    shell_script = f"""
mkdir -p /workspace/screenshots

# Dummy operation to trigger LibreOffice redraw in same session
DISPLAY=:99 xdotool search --name 'LibreOffice' windowactivate --sync 2>/dev/null || true
sleep 0.5

# Now take screenshot in SAME shell session - MUST use DISPLAY=:99 inline
# Use import (ImageMagick) instead of scrot as it is more reliable with Xvfb
DISPLAY=:99 import -window root /tmp/screenshot.png
cp /tmp/screenshot.png {container_path}

# Return as base64
python3 -c "
import base64
with open('/tmp/screenshot.png', 'rb') as f:
    print(base64.b64encode(f.read()).decode('utf-8'))
"
"""
    
    result = ctx.sandbox_manager.execute_command(["sh", "-c", shell_script])
    
    if result['exit_code'] != 0:
        error_msg = result['error'] or result['output']
        raise RuntimeError(f"Screenshot failed: {error_msg}")
    
    return result['output'].strip()


@mcp.tool()
def click(x: int, y: int) -> str:
    """Click mouse at coordinates."""
    ctx = get_context()
    
    result = ctx.sandbox_manager.execute_command([
        "sh", "-c",
        f"DISPLAY=:99 xdotool mousemove {x} {y} click 1"
    ])
    
    if result['exit_code'] != 0:
        raise RuntimeError(f"Click failed: {result['error']}")
    
    # Add delay for GUI to process
    import time
    time.sleep(0.3)
    
    # Force window refresh to update display buffer
    ctx.sandbox_manager.execute_command([
        "sh", "-c",
        "DISPLAY=:99 xdotool search --name 'LibreOffice' windowactivate --sync"
    ])
    
    return f"Clicked at ({x}, {y})"


@mcp.tool()
def double_click(x: int, y: int) -> str:
    """Double-click mouse at coordinates."""
    ctx = get_context()
    
    result = ctx.sandbox_manager.execute_command([
        "sh", "-c",
        f"DISPLAY=:99 xdotool mousemove {x} {y} click --repeat 2 --delay 100 1"
    ])
    
    if result['exit_code'] != 0:
        raise RuntimeError(f"Double-click failed: {result['error']}")
    
    # Add delay for GUI to process
    import time
    time.sleep(0.3)
    
    # Force window refresh to update display buffer
    ctx.sandbox_manager.execute_command([
        "sh", "-c",
        "DISPLAY=:99 xdotool search --name 'LibreOffice' windowactivate --sync"
    ])
    
    return f"Double-clicked at ({x}, {y})"


@mcp.tool()
def type_text(text: str) -> str:
    """
    Type text at the current cursor position (for computer use mode).
    
    Args:
        text: Text to type
    
    Returns:
        Success message
    """
    ctx = get_context()
    
    # Escape text for shell
    escaped_text = text.replace("'", "'\\''")
    
    result = ctx.sandbox_manager.execute_command([
        "sh", "-c",
        f"DISPLAY=:99 xdotool type '{escaped_text}'"
    ])
    
    if result['exit_code'] != 0:
        raise RuntimeError(f"Type failed: {result['error']}")
    
    # Add delay for GUI to process
    import time
    time.sleep(0.3)
    
    # Force window refresh to update display buffer
    ctx.sandbox_manager.execute_command([
        "sh", "-c",
        "DISPLAY=:99 xdotool search --name 'LibreOffice' windowactivate --sync"
    ])
    
    return f"Typed: {text}"


@mcp.tool()
def press_key(key: str) -> str:
    """
    Press a keyboard key or key combination (for computer use mode).
    
    Args:
        key: Key to press (e.g., "Return", "ctrl+s", "Tab")
    
    Returns:
        Success message
    """
    ctx = get_context()
    
    result = ctx.sandbox_manager.execute_command([
        "sh", "-c",
        f"DISPLAY=:99 xdotool key {key}"
    ])
    
    if result['exit_code'] != 0:
        raise RuntimeError(f"Key press failed: {result['error']}")
    
    # Add delay for GUI to process
    import time
    time.sleep(0.3)
    
    # Force window refresh to update display buffer
    ctx.sandbox_manager.execute_command([
        "sh", "-c",
        "DISPLAY=:99 xdotool search --name 'LibreOffice' windowactivate --sync"
    ])
    
    return f"Pressed: {key}"


@mcp.tool()
def goto_cell(cell: str) -> str:
    """
    Navigate to a specific cell using keyboard (more reliable than clicking).
    IMPORTANT: Only navigate to ONE cell per tool call. Take a screenshot after to verify.
    
    Args:
        cell: Cell reference like "C2", "A1", etc.
    
    Returns:
        Success message with current cell location
    """
    ctx = get_context()
    import time
    
    # Parse cell reference (e.g., "C2" -> column C, row 2)
    import re
    match = re.match(r'^([A-Z]+)(\d+)$', cell.upper())
    if not match:
        raise ValueError(f"Invalid cell reference: {cell}")
    
    col_letters, row_num = match.groups()
    
    # First, go to A1 with Ctrl+Home (guaranteed starting point)
    result = ctx.sandbox_manager.execute_command([
        "sh", "-c",
        "DISPLAY=:99 xdotool key ctrl+Home"
    ])
    
    if result['exit_code'] != 0:
        raise RuntimeError(f"Failed to go to A1: {result['error']}")
    
    time.sleep(0.3)
    
    # Navigate to target column (A=0, B=1, C=2, etc.)
    col_index = 0
    for char in col_letters:
        col_index = col_index * 26 + (ord(char) - ord('A'))
    
    if col_index > 0:
        # Press Right arrow col_index times
        for _ in range(col_index):
            result = ctx.sandbox_manager.execute_command([
                "sh", "-c",
                "DISPLAY=:99 xdotool key Right"
            ])
            time.sleep(0.1)
    
    # Navigate to target row (rows are 1-indexed)
    target_row = int(row_num)
    if target_row > 1:
        # Press Down arrow (target_row - 1) times
        for _ in range(target_row - 1):
            result = ctx.sandbox_manager.execute_command([
                "sh", "-c",
                "DISPLAY=:99 xdotool key Down"
            ])
            time.sleep(0.1)
    
    time.sleep(0.3)
    
    return f"Navigated to cell {cell.upper()}"


@mcp.tool()
def navigate_arrow(direction: str, count: int = 1) -> str:
    """
    Move cursor using arrow keys.
    
    Args:
        direction: One of "up", "down", "left", "right"
        count: Number of times to press the arrow key (default: 1)
    
    Returns:
        Success message
    """
    ctx = get_context()
    
    direction_map = {
        "up": "Up",
        "down": "Down", 
        "left": "Left",
        "right": "Right"
    }
    
    if direction.lower() not in direction_map:
        raise ValueError(f"Invalid direction: {direction}. Use: up, down, left, right")
    
    key = direction_map[direction.lower()]
    
    # Press arrow key multiple times if needed
    for _ in range(count):
        result = ctx.sandbox_manager.execute_command([
            "sh", "-c",
            f"DISPLAY=:99 xdotool key {key}"
        ])
        
        if result['exit_code'] != 0:
            raise RuntimeError(f"Failed to press {key}: {result['error']}")
        
        import time
        time.sleep(0.2)
    
    return f"Moved {direction} {count} time(s)"


@mcp.tool()
def enter_edit_mode() -> str:
    """
    Enter edit mode in the current cell (equivalent to double-clicking or pressing F2).
    
    Returns:
        Success message
    """
    ctx = get_context()
    
    result = ctx.sandbox_manager.execute_command([
        "sh", "-c",
        "DISPLAY=:99 xdotool key F2"
    ])
    
    if result['exit_code'] != 0:
        raise RuntimeError(f"Failed to enter edit mode: {result['error']}")
    
    import time
    time.sleep(0.3)
    
    return "Entered edit mode"


@mcp.tool()
def reset_environment() -> str:
    """
    Reset the sandbox environment (stop and remove container).
    Useful for starting fresh on a new task.
    
    Returns:
        Status message
    """
    ctx = get_context()
    
    ctx.sandbox_manager.cleanup()
    
    # Clear context
    from utils import clear_context
    clear_context()
    
    return "Environment reset successfully"


#diff modes use diff toolsets
def get_tool_use_tools() -> dict:
    """Get all tool-use mode MCP tools."""
    return {
        "read_cell": read_cell,
        "read_range": read_range,
        "write_cell": write_cell,
        "write_formula": write_formula,
        "get_spreadsheet_info": get_spreadsheet_info,
        "list_workspace_files": list_workspace_files,
        "execute_sql": execute_sql,
        "list_database_tables": list_database_tables,
        "create_new_spreadsheet": create_new_spreadsheet,
        "get_task_description": get_task_description,
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
        "goto_cell": goto_cell,
        "navigate_arrow": navigate_arrow,
        "enter_edit_mode": enter_edit_mode,
        "list_workspace_files": list_workspace_files,
        "get_task_description": get_task_description,
        "submit_task": submit_task
    }


if __name__ == "__main__":
    # Run the MCP server
    mcp.run()
