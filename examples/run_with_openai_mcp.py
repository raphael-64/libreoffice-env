#!/usr/bin/env python3
"""Run task with OpenAI using MCP protocol."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import argparse
import logging
import os
import asyncio
import json
from dotenv import load_dotenv

load_dotenv()

from episode_api import start_episode, end_episode, get_task_info
from examples.mcp_client import MCPClient
from openai import OpenAI

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


async def run_task(task_id: str):
    """Run task using MCP protocol."""
    if not os.getenv("OPENAI_API_KEY"):
        print("Error: OPENAI_API_KEY not set")
        return False
    
    # Start episode (Python API)
    task_def = get_task_info(task_id)
    episode_info = start_episode(task_id)
    
    logger.info(f"Episode started: {episode_info['run_dir']}")
    
    try:
        # Connect MCP subprocess
        async with MCPClient() as mcp:
            await mcp.connect_to_server(str(Path(__file__).parent.parent / "mcp_server.py"), env={
                'MCP_EPISODE_TASK_ID': task_id,
                'MCP_EPISODE_RUN_DIR': str(episode_info['run_dir']),
                'MCP_CONTAINER_ID': episode_info['container_id']
            })
            
            tools = mcp.get_tools_for_openai()
            client = OpenAI()
            
            messages = [
                {"role": "system", "content": "Solve spreadsheet tasks using MCP tools."},
                {"role": "user", "content": f"{task_def['description']}\n\nCall submit_task() when done."}
            ]
            
            # Agent loop
            for turn in range(30):
                response = client.chat.completions.create(
                    model="gpt-4o", messages=messages, tools=tools, tool_choice="auto"
                )
                
                msg = response.choices[0].message
                messages.append(msg.model_dump())
                
                if msg.tool_calls:
                    for tc in msg.tool_calls:
                        name = tc.function.name
                        args = json.loads(tc.function.arguments)
                        
                        logger.info(f"{name}({list(args.keys())})")
                        
                        try:
                            result = await mcp.call_tool(name, args)
                            result_str = str(result)
                            
                            if name == "submit_task":
                                rd = json.loads(result_str)
                                if "score" in rd:
                                    print(f"\nScore: {rd['score']} - {rd['feedback']}")
                                    return rd['passed']
                        except Exception as e:
                            result_str = f"Error: {e}"
                            logger.error(f"{e}")
                        
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": result_str
                        })
                
                elif msg.content and any(w in msg.content.lower() for w in ['done', 'completed']):
                    break
                
                if not msg.tool_calls and not msg.content:
                    break
            
            return False
    finally:
        end_episode(cleanup=False)


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-id", required=True)
    args = parser.parse_args()
    
    try:
        success = await run_task(args.task_id)
        sys.exit(0 if success else 1)
    except Exception as e:
        logger.exception("Failed")
        end_episode(cleanup=False)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
