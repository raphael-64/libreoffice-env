"""Proper MCP client implementation using MCP SDK."""
import asyncio
import logging
from typing import Optional, Any
from contextlib import AsyncExitStack

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

logger = logging.getLogger(__name__)


class MCPClient:
    """
    Proper MCP client that connects to MCP server via stdio protocol.
    
    This uses the actual MCP protocol (JSON-RPC 2.0) instead of
    directly importing Python functions.
    """
    
    def __init__(self):
        """Initialize MCP client."""
        self.session: Optional[ClientSession] = None
        self.exit_stack = AsyncExitStack()
        self.tools = []
    
    async def connect_to_server(self, server_script_path: str, env: dict | None = None):
        """
        Connect to an MCP server.
        
        Args:
            server_script_path: Path to the server script (.py or .js)
            env: Environment variables to pass to server subprocess
        """
        is_python = server_script_path.endswith('.py')
        is_js = server_script_path.endswith('.js')
        
        if not (is_python or is_js):
            raise ValueError("Server script must be a .py or .js file")
        
        command = "python" if is_python else "node"
        
        # Merge with parent environment if env provided
        server_env = None
        if env:
            import os
            server_env = os.environ.copy()
            server_env.update(env)
        
        server_params = StdioServerParameters(
            command=command,
            args=[server_script_path],
            env=server_env
        )
        
        # Start server and connect via stdio
        stdio_transport = await self.exit_stack.enter_async_context(
            stdio_client(server_params)
        )
        stdio, write = stdio_transport
        
        # Create session
        self.session = await self.exit_stack.enter_async_context(
            ClientSession(stdio, write)
        )
        
        # Initialize MCP session
        await self.session.initialize()
        
        # List available tools
        response = await self.session.list_tools()
        self.tools = response.tools
        
        logger.info(f"Connected to MCP server with {len(self.tools)} tools: {[t.name for t in self.tools]}")
    
    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        """
        Call a tool via MCP protocol.
        
        Args:
            tool_name: Name of the tool to call
            arguments: Tool arguments
        
        Returns:
            Tool result
        """
        if self.session is None:
            raise RuntimeError("Not connected to server. Call connect_to_server() first.")
        
        logger.debug(f"Calling tool: {tool_name}({arguments})")
        
        result = await self.session.call_tool(tool_name, arguments)
        
        # Extract content from result
        if hasattr(result, 'content') and result.content:
            # MCP returns TextContent or ImageContent
            content_items = []
            for item in result.content:
                if hasattr(item, 'text'):
                    content_items.append(item.text)
                elif hasattr(item, 'data'):
                    content_items.append(item.data)
            return '\n'.join(str(c) for c in content_items) if content_items else str(result.content)
        
        return result
    
    def get_tools_for_openai(self) -> list[dict]:
        """
        Convert MCP tools to OpenAI function calling format.
        
        Returns:
            List of tool definitions for OpenAI
        """
        openai_tools = []
        
        for tool in self.tools:
            openai_tools.append({
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description or "",
                    "parameters": tool.inputSchema
                }
            })
        
        return openai_tools
    
    async def cleanup(self):
        """Clean up resources."""
        await self.exit_stack.aclose()
    
    async def __aenter__(self):
        """Context manager entry."""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        await self.cleanup()

