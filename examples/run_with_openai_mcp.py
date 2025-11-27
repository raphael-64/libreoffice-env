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

# Configure logging - INFO for our code, silence noisy libraries
logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s: %(message)s'
)

# Silence noisy HTTP/library logs
logging.getLogger('httpcore').setLevel(logging.WARNING)
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('openai').setLevel(logging.WARNING)
logging.getLogger('docker').setLevel(logging.WARNING)
logging.getLogger('urllib3').setLevel(logging.WARNING)

logger = logging.getLogger(__name__)


async def run_task(task_id: str, cleanup: bool = False):
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
            
            # Build appropriate system prompt based on task mode
            if task_def.get("mode") == "computer_use":
                system_prompt = """You are a computer use agent. You interact with LibreOffice Calc through a GUI using screenshots and keyboard.

STARTING STATE:
- Spreadsheet opens with cursor at cell A1
- Use arrow keys to navigate: navigate_arrow("right", 2) moves 2 cells right
- Or use goto_cell("C2") to jump directly to a cell

ABSOLUTE RULE: Take a screenshot after EVERY SINGLE action to verify it worked!

WORKFLOW FOR EDITING ONE CELL (with mandatory screenshots):
1. take_screenshot() - see current state
2. goto_cell("C2") - navigate to cell
3. take_screenshot() - verify we're at C2
4. enter_edit_mode() - start editing
5. take_screenshot() - verify edit mode active
6. type_text("OK") - type content
7. take_screenshot() - verify "OK" is typed
8. press_key("Return") - confirm entry
9. take_screenshot() - verify cell now shows "OK"
10. Repeat for next cell

CRITICAL RULES:
- Do exactly ONE action per turn, then take a screenshot
- NEVER do multiple actions without screenshots between them
- Always verify with screenshot that your action worked before proceeding
- If screenshot shows nothing changed, try a different approach

Example turn sequence:
Turn 1: take_screenshot()
Turn 2: goto_cell("C2")
Turn 3: take_screenshot()
Turn 4: enter_edit_mode()
Turn 5: take_screenshot()
Turn 6: type_text("OK")
Turn 7: take_screenshot()
Turn 8: press_key("Return")
Turn 9: take_screenshot()
Turn 10: goto_cell("C3")
Turn 11: take_screenshot()
... continue for each cell"""
            else:
                system_prompt = "Solve spreadsheet tasks using MCP tools."
            
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"{task_def['description']}\n\nCall submit_task() when done."}
            ]
            
            # Agent loop
            for turn in range(30):
                logger.info(f"\n{'='*60}\nTurn {turn + 1}\n{'='*60}")
                
                response = client.chat.completions.create(
                    model="gpt-4o", messages=messages, tools=tools, tool_choice="auto"
                )
                
                msg = response.choices[0].message
                messages.append(msg.model_dump())
                
                # Log assistant's reasoning/text response in full
                if msg.content:
                    logger.info(f"\n{'='*60}")
                    logger.info(f"ASSISTANT REASONING:")
                    logger.info(f"{'='*60}")
                    logger.info(msg.content)
                    logger.info(f"{'='*60}\n")
                
                if msg.tool_calls:
                    # Track screenshots to inject as user messages after tool responses
                    screenshots_to_inject = []
                    
                    for tc in msg.tool_calls:
                        name = tc.function.name
                        args = json.loads(tc.function.arguments)
                        
                        # Log the actual tool call with arguments
                        args_str = json.dumps(args, indent=2)
                        logger.info(f"\n{name}({args_str})")
                        
                        try:
                            result = await mcp.call_tool(name, args)
                            result_str = str(result)
                            
                            # Log the result
                            if len(result_str) > 500:
                                logger.info(f"Result: {result_str[:500]}... (truncated)")
                            else:
                                logger.info(f"Result: {result_str}")
                            
                            if name == "submit_task":
                                rd = json.loads(result_str)
                                if "score" in rd:
                                    print(f"\nScore: {rd['score']} - {rd['feedback']}")
                                    return rd['passed']
                        except Exception as e:
                            result_str = f"Error: {e}"
                            logger.error(f"{name} failed: {e}")
                        
                        # Collect screenshots for later injection
                        if name == "take_screenshot" and result_str and not result_str.startswith("Error"):
                            screenshots_to_inject.append(result_str)
                            messages.append({
                                "role": "tool",
                                "tool_call_id": tc.id,
                                "content": "Screenshot captured successfully"
                            })
                        else:
                            messages.append({
                                "role": "tool",
                                "tool_call_id": tc.id,
                                "content": result_str
                            })
                    
                    # Inject screenshots as user messages (OpenAI requires images in user role)
                    for screenshot_b64 in screenshots_to_inject:
                        messages.append({
                            "role": "user",
                            "content": [
                                {
                                    "type": "image_url",
                                    "image_url": {
                                        "url": f"data:image/png;base64,{screenshot_b64}"
                                    }
                                }
                            ]
                        })
                
                elif msg.content and any(w in msg.content.lower() for w in ['done', 'completed']):
                    break
                
                if not msg.tool_calls and not msg.content:
                    break
            
            return False
    finally:
        end_episode(cleanup=cleanup)


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--cleanup", action="store_true", 
                        help="Delete run directory after completion")
    args = parser.parse_args()
    
    try:
        success = await run_task(args.task_id, cleanup=args.cleanup)
        sys.exit(0 if success else 1)
    except Exception as e:
        logger.exception("Failed")
        end_episode(cleanup=args.cleanup)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
