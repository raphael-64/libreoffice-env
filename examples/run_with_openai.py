#!/usr/bin/env python3
"""Run episodes with OpenAI agent."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import argparse
import logging
import os
from dotenv import load_dotenv

load_dotenv()

from orchestration.env_runner import EpisodeRunner
from orchestration.task_manager import TaskManager
from examples.openai_agent import MCPAgent

# Import MCP tools
from mcp_server import (
    read_cell, write_cell, write_formula, 
    get_spreadsheet_info, list_workspace_files,
    get_task_description, submit_task, reset_environment
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def run_automated_episode(task_id: str, episode_num: int | None = None):
    """Run a complete automated episode with AI agent."""
    
    print("\n" + "="*70)
    print(" AUTOMATED EPISODE TEST - Real Agent Solving Task")
    print("="*70 + "\n")
    
    # Check API key
    if not os.getenv("OPENAI_API_KEY"):
        print("Error: OPENAI_API_KEY not set")
        print("   Run: export OPENAI_API_KEY=your_key_here")
        return False
    
    # Initialize
    runner = EpisodeRunner()
    tm = TaskManager()
    
    # Load task
    task_def = tm.load_task(task_id)
    
    print(f"Task: {task_def['title']}")
    print(f"Description: {task_def['description']}")
    print()
    
    # Start episode
    print(f"Starting episode {episode_num or 'auto'}...")
    sandbox, run_dir, task_def = runner.start_episode(task_id, episode_num)
    print(f"   Run directory: {run_dir}")
    print(f"   Container started")
    print()
    
    # Set global context for MCP tools
    import mcp_server
    mcp_server.sandbox_manager = sandbox
    mcp_server.current_task_id = task_id
    mcp_server.current_run_dir = run_dir
    mcp_server.task_manager = tm
    
    # Check task mode
    task_mode = task_def.get('mode', 'tool_use')
    
    # Select tools based on mode
    from mcp_server import get_tool_use_tools, get_computer_use_tools
    
    if task_mode == 'computer_use':
        mcp_tools = get_computer_use_tools()
        use_vision = True
        
        # Start GUI
        print("Starting GUI mode...")
        initial_file = task_def.get('initial_files', [None])[0]
        if initial_file:
            sandbox.start_gui(initial_file)
            print(f"   LibreOffice opened with {initial_file}\n")
    else:
        mcp_tools = get_tool_use_tools()
        use_vision = False
    
    # Create agent with optional screenshot saving
    agent = MCPAgent(
        mcp_tools, 
        model="gpt-4o", 
        use_vision=use_vision,
        save_screenshots=True,  # Save screenshots for debugging
        screenshot_dir=str(run_dir / "screenshots")
    )
    
    print(f"Agent initialized (GPT-4)")
    print(f"Tools available: {list(mcp_tools.keys())}")
    print()
    
    # Construct task prompt
    task_prompt = f"""
{task_def['description']}

Available files: {list(tm.get_initial_files(task_id).keys())}
Time limit: {task_def['time_limit_seconds']} seconds

Use the provided MCP tools to:
1. Explore the spreadsheet
2. Read the necessary data
3. Perform calculations
4. Write your results
5. Call submit_task() when done to get graded

Please solve this task step by step.
"""
    
    print("Sending task to agent...\n")
    print("-"*70)
    print(task_prompt)
    print("-"*70 + "\n")
    
    try:
        # Agent solves task
        print("Agent working...\n")
        result = agent.solve_task(task_prompt, max_turns=30)
        
        print("\n" + "="*70)
        print(" EPISODE RESULTS")
        print("="*70 + "\n")
        
        if result['success']:
            grading = result['grading']
            print(f"Agent completed task!")
            print(f"Grading Results:")
            print(f"   Passed: {grading['passed']}")
            print(f"   Score: {grading['score']} ({grading['score']*100:.1f}%)")
            print(f"   Feedback: {grading['feedback']}")
            print(f"\nStats:")
            print(f"   Turns taken: {result['turns']}")
            
            if grading.get('details'):
                details = grading['details']
                print(f"   Cells graded: {details['total_cells']}")
                print(f"   Correct: {details['correct_cells']}")
                
                if details.get('errors'):
                    print(f"\nErrors ({len(details['errors'])}):")
                    for error in details['errors'][:5]:
                        print(f"      {error}")
        else:
            print(f"Agent failed to complete task")
            print(f"   Error: {result.get('error', 'Unknown')}")
            print(f"   Turns: {result['turns']}")
        
        print("\n" + "="*70 + "\n")
        
        return result['success']
        
    except Exception as e:
        logger.exception("Episode failed")
        return False
    
    finally:
        # Cleanup
        runner.current_sandbox = sandbox
        runner.current_run_dir = run_dir
        runner.end_episode(grade=False)
        print("Episode ended, container cleaned up\n")


def main():
    parser = argparse.ArgumentParser(description="Run automated episode with AI agent")
    parser.add_argument("--task-id", required=True, help="Task ID to run")
    parser.add_argument("--episode", type=int, help="Episode number")
    parser.add_argument("--model", default="gpt-4o", help="OpenAI model (default: gpt-4o)")
    args = parser.parse_args()
    
    success = run_automated_episode(args.task_id, args.episode)
    
    if success:
        print("SUCCESS: Agent solved the task and passed grading.\n")
    else:
        print("FAILED: Agent couldn't solve the task.\n")
    
    exit(0 if success else 1)


if __name__ == "__main__":
    main()

