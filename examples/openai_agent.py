"""Agent client that uses OpenAI to solve tasks via MCP tools."""
import json
import logging
from typing import Any, Dict, List
from openai import OpenAI

logger = logging.getLogger(__name__)


class MCPAgent:
    """Agent client using OpenAI function calling with MCP tools."""
    
    def __init__(self, mcp_tools: Dict[str, Any], model: str = "gpt-4o", use_vision: bool = False, 
                 save_screenshots: bool = False, screenshot_dir: str = "screenshots"):
        self.mcp_tools = mcp_tools
        self.model = model
        self.use_vision = use_vision
        self.save_screenshots = save_screenshots
        self.screenshot_dir = screenshot_dir
        self.screenshot_count = 0
        self.client = OpenAI()  # Reads OPENAI_API_KEY from env
        
        # Setup screenshot directory if saving
        if save_screenshots:
            from pathlib import Path
            Path(screenshot_dir).mkdir(exist_ok=True)
        
        # Convert MCP tools to OpenAI format
        self.openai_tools = self._convert_tools_to_openai_format()
    
    def _convert_tools_to_openai_format(self) -> List[Dict]:
        """Convert MCP tools to OpenAI function calling format."""
        openai_tools = []
        
        for tool_name, tool_func in self.mcp_tools.items():
            # Get function signature and docstring
            import inspect
            sig = inspect.signature(tool_func)
            doc = inspect.getdoc(tool_func) or ""
            
            # Parse parameters
            parameters = {
                "type": "object",
                "properties": {},
                "required": []
            }
            
            for param_name, param in sig.parameters.items():
                # Skip self/cls
                if param_name in ('self', 'cls'):
                    continue
                
                # Determine parameter type
                param_schema = {"description": f"Parameter {param_name}"}
                
                if param.annotation != inspect.Parameter.empty:
                    annotation_str = str(param.annotation)
                    
                    if "int" in annotation_str:
                        param_schema["type"] = "integer"
                    elif "list" in annotation_str:
                        param_schema["type"] = "array"
                        # Array requires items schema
                        if "str" in annotation_str:
                            param_schema["items"] = {"type": "string"}
                        else:
                            param_schema["items"] = {"type": "string"}  # Default
                    elif "dict" in annotation_str:
                        param_schema["type"] = "object"
                    else:
                        param_schema["type"] = "string"
                else:
                    param_schema["type"] = "string"
                
                parameters["properties"][param_name] = param_schema
                
                # Required if no default
                if param.default == inspect.Parameter.empty:
                    parameters["required"].append(param_name)
            
            openai_tools.append({
                "type": "function",
                "function": {
                    "name": tool_name,
                    "description": doc.split('\n')[0],  # First line of docstring
                    "parameters": parameters
                }
            })
        
        return openai_tools
    
    def solve_task(self, task_description: str, max_turns: int = 20) -> Dict[str, Any]:
        """
        Solve a task using MCP tools.
        
        Args:
            task_description: Task description to give the agent
            max_turns: Maximum conversation turns
        
        Returns:
            Dict with success status and conversation history
        """
        # System message
        if self.use_vision:
            system_msg = ("You are solving tasks using a computer GUI. "
                         "You can see screenshots and use mouse/keyboard. "
                         "When done, call submit_task().")
        else:
            system_msg = ("You are solving spreadsheet tasks programmatically. "
                         "Use the provided tools to read and write data. "
                         "When done, call submit_task().")
        
        # Initial message
        if self.use_vision:
            # Get initial screenshot
            screenshot_b64 = self.mcp_tools.get('take_screenshot', lambda: None)()
            if screenshot_b64 and not screenshot_b64.startswith("Error"):
                # Optionally save screenshot
                if self.save_screenshots:
                    self._save_screenshot(screenshot_b64, f"turn_0_initial")
                
                user_content = [
                    {"type": "text", "text": task_description},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{screenshot_b64}"}}
                ]
            else:
                user_content = task_description
        else:
            user_content = task_description
        
        messages = [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_content}
        ]
        
        logger.info(f"Agent starting task with {len(self.openai_tools)} tools available")
        
        for turn in range(max_turns):
            logger.info(f"Turn {turn+1}/{max_turns}")
            
            # Call OpenAI
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=self.openai_tools,
                tool_choice="auto"
            )
            
            message = response.choices[0].message
            messages.append(message.model_dump())
            
            # Check if wants to call tools
            if message.tool_calls:
                logger.info(f"Agent wants to call {len(message.tool_calls)} tool(s)")
                
                # Execute each tool call
                for tool_call in message.tool_calls:
                    tool_name = tool_call.function.name
                    tool_args = json.loads(tool_call.function.arguments)
                    
                    logger.info(f"  Calling: {tool_name}({tool_args})")
                    
                    # Execute the MCP tool
                    try:
                        result = self.mcp_tools[tool_name](**tool_args)
                        result_str = json.dumps(result) if isinstance(result, dict) else str(result)
                        logger.info(f"  Result: {result_str[:100]}")
                        
                        # Check if this was submit_task
                        if tool_name == "submit_task" and isinstance(result, dict):
                            if "score" in result:
                                logger.info(f"  🎓 Task submitted! Score: {result['score']}")
                                return {
                                    "success": True,
                                    "grading": result,
                                    "turns": turn + 1,
                                    "messages": messages
                                }
                    
                    except Exception as e:
                        result_str = f"Error: {str(e)}"
                        logger.error(f"  Tool error: {e}")
                    
                    # Add tool result to conversation
                    tool_message = {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": result_str
                    }
                    messages.append(tool_message)
                
                # If vision mode, take new screenshot after actions
                if self.use_vision and message.tool_calls:
                    screenshot_b64 = self.mcp_tools.get('take_screenshot', lambda: None)()
                    if screenshot_b64 and not screenshot_b64.startswith("Error"):
                        # Optionally save screenshot
                        if self.save_screenshots:
                            self._save_screenshot(screenshot_b64, f"turn_{turn+1}_after_actions")
                        
                        # Add screenshot after tool results
                        messages.append({
                            "role": "user",
                            "content": [
                                {"type": "text", "text": "Screenshot after actions:"},
                                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{screenshot_b64}"}}
                            ]
                        })
            
            # Check if done (no more tool calls)
            elif message.content:
                logger.info(f"Agent response: {message.content[:100]}")
                
                # Check if agent thinks it's done
                if any(word in message.content.lower() for word in ['done', 'completed', 'finished']):
                    logger.info("Agent says it's done, but didn't call submit_task")
                    break
            
            # Stop if no tool calls and no content
            if not message.tool_calls and not message.content:
                break
        
        return {
            "success": False,
            "error": "Agent didn't submit task",
            "turns": turn + 1,
            "messages": messages
        }
    
    def _save_screenshot(self, screenshot_b64: str, name: str) -> None:
        """Save screenshot to disk for debugging."""
        import base64
        from pathlib import Path
        
        img_data = base64.b64decode(screenshot_b64)
        screenshot_path = Path(self.screenshot_dir) / f"{name}.png"
        screenshot_path.write_bytes(img_data)
        logger.info(f"Saved screenshot: {screenshot_path}")

