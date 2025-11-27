#!/usr/bin/env python3
"""Simple Python API usage (no MCP protocol)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from episode_api import start_episode, end_episode, list_tasks
from mcp_server import get_tool_use_tools

# List tasks
print("Available tasks:", list_tasks())
print()

# Start episode
info = start_episode("sales_totals")
print(f"Task: {info['task_id']}")
print(f"Run dir: {info['run_dir']}")
print()

# Get tools (direct Python import)
tools = get_tool_use_tools()

# Use tools
files = tools['list_workspace_files']()
print(f"Files: {files}")

if files:
    sheet_info = tools['get_spreadsheet_info'](files[0])
    print(f"\nSpreadsheet: {files[0]}")
    for sheet in sheet_info['sheets']:
        print(f"  {sheet['name']}: {sheet['rows']}x{sheet['cols']}")

# Cleanup
end_episode(cleanup=False)
print(f"\nRun saved at: {info['run_dir']}")
