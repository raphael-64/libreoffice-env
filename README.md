# LibreOffice RL Environment

MCP-based sandboxed environment for training AI agents on spreadsheet tasks.
Tool-use is implemented and reliable, computer-use has been started but not fully working.

## Setup

### Prerequisites

- Docker Desktop (running)
- Python 3.12+
- uv package manager
- optional OpenAI API key (in `.env` file) if you want to test the env

### Install

```bash
uv sync
docker build -t libreoffice-sandbox:latest sandbox/
```

## Architecture

```
tasks/               # Task definitions
  {task_id}/
    task.json        # Problem statement
    initial/         # Starting files
    oracle/          # Expected outputs

runs/                # Episode runs (auto-generated)
  {task_id}/
    run_001/         # Episode 1
    run_002/         # Episode 2
```

**One base Docker image** → Used for ALL episodes
**Fresh files** → Copied from `tasks/initial/` each episode
**Isolated execution** → Each episode in separate run directory

## Quick Start

```python
from libreoffice_env import LibreOfficeEnv
from mcp_server import get_tool_use_tools

env = LibreOfficeEnv()
state = env.reset("sales_totals")

# Your agent acts using MCP tools
tools = get_tool_use_tools()
# tools = {read_cell, write_cell, write_formula, execute_sql, ...}

# After agent acts, get reward
score = env.get_reward()
env.close(cleanup=True)
```

### Run Example with OpenAI

```bash
python examples/run_with_openai.py --task-id sales_totals
```

This will:

1. Create run directory with fresh files
2. Start container
3. Send task to GPT-4
4. Agent uses MCP tools to solve
5. Automatic grading vs oracle
6. Return score + feedback

### Create New Task

```python
from orchestration.task_manager import TaskManager

tm = TaskManager()
tm.create_task(
    task_id="my_task",
    title="Task Title",
    description="Clear instructions for agent...",
    initial_files={"data.ods": Path("input.ods")},
    oracle_files={"data.ods": Path("expected.ods")},
    time_limit=600
)
```

### Use with Your Own Agent

```python
from orchestration.env_runner import EpisodeRunner

runner = EpisodeRunner()

for i in range(10):
    # Start episode - gets fresh files
    sandbox, run_dir, task = runner.start_episode("sales_totals")

    # Your agent solves the task using MCP tools
    # (Connect to mcp_server.py or use tools directly)

    # Grade when done
    result = runner.end_episode(grade=True, cleanup=True)
    print(f"Episode {i}: Score {result['score']}")
```

See `examples/run_with_openai.py` for a complete OpenAI agent implementation.

## MCP Tools (15 total)

**Tool Use Mode (Production):**

- `read_cell`, `write_cell`, `write_formula` - Spreadsheet operations
- `execute_sql`, `list_database_tables` - SQLite queries
- `create_new_spreadsheet` - File creation
- `get_spreadsheet_info`, `list_workspace_files` - Discovery
- `get_task_description`, `submit_task` - Task workflow

**Computer Use Mode (Experimental):**

- `take_screenshot`, `click`, `double_click` - GUI interaction
- `type_text`, `press_key` - Keyboard control
- **Note:** Infrastructure in place but LibreOffice GUI interaction needs debugging

## Project Structure

```
libreoffice-env/
├── mcp_server.py                # MCP server with 15 tools
├── orchestration/               # Core environment
│   ├── sandbox_manager.py       # Docker lifecycle
│   ├── task_manager.py          # Task loading
│   └── env_runner.py            # Episode management
├── evaluation/
│   └── grader.py                # Automated grading
├── examples/                    # Example usage
│   ├── openai_agent.py          # OpenAI-based agent
│   └── run_with_openai.py       # Run episodes with OpenAI
├── tasks/                       # Task definitions
└── sandbox/                     # Docker image
```
