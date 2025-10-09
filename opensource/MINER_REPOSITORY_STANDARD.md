# Autoppia Miner Repository Standard

## Overview

This document defines the standard structure that miner repositories must follow to be compatible with the Autoppia Deployment Controller. Miners must structure their GitHub repositories according to this standard to enable automatic deployment and testing.

## Repository Structure

```
miner-repository/
├── docker-compose.yml          # Required: Main deployment configuration
├── .env.example               # Optional: Environment variables template
├── README.md                  # Required: Repository documentation
├── agent/                     # Required: Agent implementation directory
│   ├── Dockerfile            # Required: Agent container definition
│   ├── requirements.txt      # Required: Python dependencies
│   ├── main.py              # Required: Agent entry point
│   └── ...                  # Agent-specific files
├── tests/                    # Optional: Test files
└── docs/                     # Optional: Additional documentation
```

## Required Files

### 1. `docker-compose.yml` (Required)

The main deployment configuration that defines how the miner agent should be deployed:

```yaml
version: '3.8'

services:
  agent:
    build:
      context: ./agent
      dockerfile: Dockerfile
    container_name: autoppia-miner-agent
    ports:
      - "8000:8000"  # Must expose port 8000
    environment:
      - NODE_ENV=production
      - AGENT_NAME=${AGENT_NAME:-Autoppia Miner}
      - AGENT_VERSION=${AGENT_VERSION:-1.0.0}
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s
    restart: unless-stopped
    labels:
      - "autoppia.miner=true"
      - "autoppia.version=1.0"
    networks:
      - autoppia-network

networks:
  autoppia-network:
    external: true
    name: deployer_network
```

**Key Requirements:**
- Service must be named `agent`
- Must expose port `8000` (mapped to host port)
- Must include health check endpoint
- Must use external network `deployer_network`
- Must include `autoppia.miner=true` label

### 2. `agent/Dockerfile` (Required)

Container definition for the miner agent:

```dockerfile
FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd -m -u 1000 miner && \
    mkdir -p /app && \
    chown -R miner:miner /app

# Set working directory
WORKDIR /app

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Change ownership
RUN chown -R miner:miner /app

# Switch to non-root user
USER miner

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run the application
CMD ["python", "main.py"]
```

### 3. `agent/main.py` (Required)

The main entry point for the miner agent:

```python
"""
Autoppia Miner Agent - Main Entry Point
"""
import asyncio
import os
from typing import Dict, Any, List

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import uvicorn

# Agent implementation
from .agent import AutoppiaMinerAgent

app = FastAPI(
    title="Autoppia Miner Agent",
    description="Web agent for Autoppia subnet",
    version=os.getenv("AGENT_VERSION", "1.0.0")
)

# Initialize agent
agent = AutoppiaMinerAgent()

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

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "agent_name": os.getenv("AGENT_NAME", "Autoppia Miner"),
        "version": os.getenv("AGENT_VERSION", "1.0.0")
    }

@app.post("/api/task", response_model=TaskResponse)
async def process_task(request: TaskRequest):
    """Process a task from the validator."""
    try:
        start_time = asyncio.get_event_loop().time()
        
        # Process task with agent
        actions = await agent.solve_task(
            prompt=request.prompt,
            url=request.url,
            html=request.html,
            screenshot=request.screenshot
        )
        
        execution_time = asyncio.get_event_loop().time() - start_time
        
        return TaskResponse(
            success=True,
            actions=actions,
            execution_time=execution_time,
            agent_id=os.getenv("AGENT_NAME", "Autoppia Miner")
        )
        
    except Exception as e:
        return TaskResponse(
            success=False,
            actions=[],
            execution_time=0.0,
            error=str(e),
            agent_id=os.getenv("AGENT_NAME", "Autoppia Miner")
        )

@app.get("/api/info")
async def get_agent_info():
    """Get agent information."""
    return {
        "agent_name": os.getenv("AGENT_NAME", "Autoppia Miner"),
        "version": os.getenv("AGENT_VERSION", "1.0.0"),
        "capabilities": agent.get_capabilities(),
        "github_url": os.getenv("GITHUB_URL", ""),
        "has_rl": os.getenv("HAS_RL", "false").lower() == "true"
    }

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=False
    )
```

### 4. `agent/requirements.txt` (Required)

Python dependencies for the agent:

```txt
fastapi==0.104.1
uvicorn[standard]==0.24.0
pydantic==2.5.0
httpx==0.25.2
selenium==4.15.0
beautifulsoup4==4.12.2
pillow==10.1.0
numpy==1.24.3
```

### 5. `README.md` (Required)

Repository documentation:

```markdown
# Autoppia Miner Agent

## Description
Brief description of your miner agent and its capabilities.

## Features
- List of key features
- Supported web interactions
- Special capabilities

## Quick Start
```bash
# Clone repository
git clone <your-repo-url>
cd <your-repo>

# Start with docker-compose
docker-compose up -d

# Check health
curl http://localhost:8000/health
```

## API Endpoints
- `GET /health` - Health check
- `POST /api/task` - Process task from validator
- `GET /api/info` - Agent information

## Configuration
Environment variables:
- `AGENT_NAME` - Name of your agent
- `AGENT_VERSION` - Version of your agent
- `GITHUB_URL` - URL to this repository
- `HAS_RL` - Whether agent uses reinforcement learning

## Testing
```bash
# Run tests
docker-compose exec agent python -m pytest tests/
```
```

## API Contract

### Task Request Format

```json
{
  "prompt": "Navigate to the homepage and click the login button",
  "url": "https://example.com",
  "html": "<html>...</html>",
  "screenshot": "base64-encoded-image",
  "actions": [],
  "version": "1.0.0"
}
```

### Task Response Format

```json
{
  "success": true,
  "actions": [
    {
      "type": "navigate",
      "url": "https://example.com"
    },
    {
      "type": "click",
      "selector": "button.login",
      "coordinates": [100, 200]
    }
  ],
  "execution_time": 2.5,
  "error": null,
  "agent_id": "My Custom Agent"
}
```

### Action Types

Miners must support these action types:

```python
ACTION_TYPES = {
    "navigate": {"url": str},
    "click": {"selector": str, "coordinates": [int, int]},
    "type": {"selector": str, "text": str},
    "scroll": {"direction": str, "amount": int},
    "wait": {"duration": float},
    "screenshot": {},
    "extract": {"selector": str, "attribute": str}
}
```

## Environment Variables

Miners can use these environment variables:

- `AGENT_NAME` - Display name for the agent
- `AGENT_VERSION` - Version of the agent
- `GITHUB_URL` - URL to the repository
- `HAS_RL` - Whether agent uses reinforcement learning (true/false)
- `LOG_LEVEL` - Logging level (DEBUG, INFO, WARNING, ERROR)
- `MAX_EXECUTION_TIME` - Maximum task execution time in seconds

## Validation Requirements

The deployment controller will validate:

1. **Repository Structure**
   - `docker-compose.yml` exists and is valid
   - `agent/Dockerfile` exists
   - `agent/main.py` exists
   - `agent/requirements.txt` exists
   - `README.md` exists

2. **Docker Compose**
   - Service named `agent` exists
   - Port 8000 is exposed
   - Health check is configured
   - Uses `deployer_network`
   - Has `autoppia.miner=true` label

3. **API Endpoints**
   - `GET /health` returns 200
   - `POST /api/task` accepts and processes requests
   - `GET /api/info` returns agent information

4. **Response Format**
   - Task responses match expected schema
   - Actions are valid according to action types
   - Execution time is reported

## Example Repository

See the `examples/miner-template/` directory for a complete example repository that follows this standard.

## Migration Guide

For existing miners:

1. **Add docker-compose.yml** to repository root
2. **Move agent code** to `agent/` directory
3. **Add Dockerfile** in `agent/` directory
4. **Update main.py** to use FastAPI with required endpoints
5. **Add requirements.txt** with dependencies
6. **Update README.md** with standard format
7. **Test locally** with `docker-compose up`

## Support

For questions about the repository standard:
- Check the example template
- Review the validation errors from deployment controller
- Open an issue in the Autoppia repository
