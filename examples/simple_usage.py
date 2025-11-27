#!/usr/bin/env python3
"""Simple usage example - Run from project root."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from libreoffice_env import LibreOfficeEnv

# Initialize environment
env = LibreOfficeEnv()

# List available tasks
print("Available tasks:", env.list_tasks())

# Start episode
state = env.reset("sales_totals")
print(f"\nTask: {state['description']}")
print(f"Files: {state['files']}")

# Your agent would act here using MCP tools
# For this example, we'll use the OpenAI agent

from examples.openai_agent import MCPAgent
from mcp_server import get_tool_use_tools

agent = MCPAgent(get_tool_use_tools())

result = agent.solve_task(state['description'])

# Get reward
score = env.get_reward()
print(f"\nScore: {score}")

# Cleanup
env.close(cleanup=True)

