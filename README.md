# LibreOffice RL Environment

MCP-based sandboxed environment for AI agents to practice spreadsheet tasks.

## Architecture

```
Agent → MCP Protocol → MCP Server → Docker Container (LibreOffice)
```

- **Orchestration**: Python API manages container lifecycle
- **Execution**: MCP protocol for tool calls (stdio + JSON-RPC)
- **Isolation**: Docker containers, network disabled, fresh per task

## Setup

```bash
uv sync
docker build -t libreoffice-sandbox:latest sandbox/
```

**Prerequisites:** Docker Desktop, Python 3.12+, uv, OpenAI API key (optional)

## Usage

### Basic testing with openai

```bash
python examples/run_with_openai_mcp.py --task-id sales_totals
```

## File Structure

```
mcp_server.py           # 17 MCP tools
utils.py                # CellRef + Context
spreadsheet_ops.py      # Operation scripts
grader.py               # Automated grading

orchestration/          # Internal
  ├── episode_runner.py # Episode lifecycle
  ├── sandbox_manager.py # Docker management
  └── task_manager.py    # Task loading

examples/               # Usage examples
  ├── mcp_client.py      # MCP client (SDK)
  ├── run_with_openai_mcp.py
  └── simple_mcp_usage.py

sandbox/                # Docker build
tasks/                  # Task definitions
runs/                   # Episode outputs
```

## MCP Tools (17 total)

**Spreadsheet:**

- `read_cell`, `read_range`, `write_cell`, `write_formula`
- `get_spreadsheet_info`, `create_new_spreadsheet`

**Database:**

- `execute_sql`, `list_database_tables`

**Files:**

- `list_workspace_files`

**Task:**

- `get_task_description`, `submit_task`

**GUI (experimental):**

- `take_screenshot`, `click`, `double_click`, `type_text`, `press_key`

## Available Tasks

- `sales_totals` - Calculate totals with formulas
- `banking_reserves` - Reserve calculations
- `department_summary` - Employee summary
- `sales_report` - Database to spreadsheet
- `gui_data_entry` - Computer-use mode (experimental)

## Example: MCP Protocol

```python
import asyncio
from orchestration.episode_runner import EpisodeRunner
from examples.mcp_client import MCPClient

async def solve():
    runner = EpisodeRunner()
    sandbox, run_dir, _ = runner.start_episode("sales_totals")

    async with MCPClient() as mcp:
        await mcp.connect_to_server("mcp_server.py", env={
            'MCP_CONTAINER_ID': sandbox.container_id,
            'MCP_EPISODE_RUN_DIR': str(run_dir),
            'MCP_EPISODE_TASK_ID': "sales_totals"
        })

        result = await mcp.call_tool("read_cell", {...})
        await mcp.call_tool("submit_task", {})

    runner.end_episode()

asyncio.run(solve())
```

## Creating Tasks

```python
from orchestration.task_manager import TaskManager

tm = TaskManager()
tm.create_task(
    task_id="my_task",
    title="Task Title",
    description="Instructions...",
    initial_files={"data.ods": Path("input.ods")},
    oracle_files={"data.ods": Path("expected.ods")},
    time_limit=600
)
```
