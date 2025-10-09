"""
Autoppia Miner Agent - Main Entry Point
Example implementation following the Autoppia Miner Repository Standard
"""
import asyncio
import os
import time
from typing import Dict, Any, List

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import uvicorn
from loguru import logger

# Configure logging
logger.remove()
logger.add(
    lambda msg: print(msg, end=""),
    level=os.getenv("LOG_LEVEL", "INFO")
)

app = FastAPI(
    title="Autoppia Miner Agent",
    description="Web agent for Autoppia subnet",
    version=os.getenv("AGENT_VERSION", "1.0.0")
)


class TaskRequest(BaseModel):
    """Task request from validator."""
    prompt: str
    url: str
    html: str = ""
    screenshot: str = ""
    actions: List[Dict[str, Any]] = []
    version: str = "1.0.0"


class TaskResponse(BaseModel):
    """Task response to validator."""
    success: bool
    actions: List[Dict[str, Any]]
    execution_time: float
    error: str = None
    agent_id: str = os.getenv("AGENT_NAME", "Autoppia Miner")


class AgentInfo(BaseModel):
    """Agent information response."""
    agent_name: str
    version: str
    capabilities: List[str]
    github_url: str
    has_rl: bool


class AutoppiaMinerAgent:
    """Example miner agent implementation."""

    def __init__(self):
        self.agent_name = os.getenv("AGENT_NAME", "Autoppia Miner")
        self.version = os.getenv("AGENT_VERSION", "1.0.0")
        self.github_url = os.getenv("GITHUB_URL", "")
        self.has_rl = os.getenv("HAS_RL", "false").lower() == "true"

    async def solve_task(self, prompt: str, url: str, html: str = "", screenshot: str = "") -> List[Dict[str, Any]]:
        """
        Solve a web task based on the prompt and URL.

        This is where miners implement their web agent logic.
        """
        logger.info(f"Solving task: {prompt} on {url}")

        # Example implementation - miners should replace this with their actual logic
        actions = []

        # Parse the prompt to determine actions
        prompt_lower = prompt.lower()

        if "navigate" in prompt_lower or "go to" in prompt_lower:
            actions.append({
                "type": "navigate",
                "url": url
            })

        if "click" in prompt_lower:
            # Try to find clickable elements
            if "login" in prompt_lower:
                actions.append({
                    "type": "click",
                    "selector": "button.login, .login-button, [data-testid='login']",
                    "coordinates": [100, 200]
                })
            elif "search" in prompt_lower:
                actions.append({
                    "type": "click",
                    "selector": "button.search, .search-button, [data-testid='search']",
                    "coordinates": [150, 250]
                })
            else:
                actions.append({
                    "type": "click",
                    "selector": "button, .btn, [role='button']",
                    "coordinates": [200, 300]
                })

        if "type" in prompt_lower or "enter" in prompt_lower:
            if "username" in prompt_lower or "email" in prompt_lower:
                actions.append({
                    "type": "type",
                    "selector": "input[type='email'], input[name='username'], input[placeholder*='email']",
                    "text": "test@example.com"
                })
            elif "password" in prompt_lower:
                actions.append({
                    "type": "type",
                    "selector": "input[type='password'], input[name='password']",
                    "text": "password123"
                })
            elif "search" in prompt_lower:
                actions.append({
                    "type": "type",
                    "selector": "input[type='search'], input[placeholder*='search']",
                    "text": "autoppia"
                })

        if "scroll" in prompt_lower:
            actions.append({
                "type": "scroll",
                "direction": "down",
                "amount": 500
            })

        if "screenshot" in prompt_lower or "capture" in prompt_lower:
            actions.append({
                "type": "screenshot"
            })

        if "wait" in prompt_lower:
            actions.append({
                "type": "wait",
                "duration": 2.0
            })

        # If no specific actions were determined, add a basic navigation
        if not actions:
            actions.append({
                "type": "navigate",
                "url": url
            })
            actions.append({
                "type": "screenshot"
            })

        logger.info(f"Generated {len(actions)} actions")
        return actions

    def get_capabilities(self) -> List[str]:
        """Return list of agent capabilities."""
        capabilities = [
            "web_navigation",
            "element_interaction",
            "form_filling",
            "screenshot_capture",
            "text_extraction"
        ]

        if self.has_rl:
            capabilities.append("reinforcement_learning")

        return capabilities


# Initialize agent
agent = AutoppiaMinerAgent()


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "agent_name": agent.agent_name,
        "version": agent.version,
        "timestamp": time.time()
    }


@app.post("/api/task", response_model=TaskResponse)
async def process_task(request: TaskRequest):
    """Process a task from the validator."""
    try:
        start_time = time.time()

        logger.info(f"Processing task: {request.prompt}")

        # Process task with agent
        actions = await agent.solve_task(
            prompt=request.prompt,
            url=request.url,
            html=request.html,
            screenshot=request.screenshot
        )

        execution_time = time.time() - start_time

        logger.info(f"Task completed in {execution_time:.2f}s with {len(actions)} actions")

        return TaskResponse(
            success=True,
            actions=actions,
            execution_time=execution_time,
            agent_id=agent.agent_name
        )

    except Exception as e:
        logger.error(f"Task failed: {str(e)}")
        return TaskResponse(
            success=False,
            actions=[],
            execution_time=0.0,
            error=str(e),
            agent_id=agent.agent_name
        )


@app.get("/api/info", response_model=AgentInfo)
async def get_agent_info():
    """Get agent information."""
    return AgentInfo(
        agent_name=agent.agent_name,
        version=agent.version,
        capabilities=agent.get_capabilities(),
        github_url=agent.github_url,
        has_rl=agent.has_rl
    )


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "message": "Autoppia Miner Agent",
        "agent_name": agent.agent_name,
        "version": agent.version,
        "endpoints": {
            "health": "/health",
            "task": "/api/task",
            "info": "/api/info"
        }
    }

if __name__ == "__main__":
    logger.info(f"Starting {agent.agent_name} v{agent.version}")
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        log_level=os.getenv("LOG_LEVEL", "info").lower()
    )
