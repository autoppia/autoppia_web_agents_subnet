import json
import logging
from typing import Optional

import httpx
from fastapi import FastAPI, Request, HTTPException, Response

from models import LLMUsage, DEFAULT_PROVIDER_CONFIGS
from config import (
    COST_LIMIT_ENABLED,
    COST_LIMIT_PER_TASK,
    OPENAI_API_KEY,
    CHUTES_API_KEY
)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class LLMGateway:
    """Simplified gateway for single agent evaluation"""
    
    def __init__(self): 
        self.providers = DEFAULT_PROVIDER_CONFIGS.copy()
        self.http_client = httpx.AsyncClient(timeout=60.0)
        self.allowed_task_ids = set()
        self.usage_per_task: dict[str, LLMUsage] = {}
    
    def detect_provider(self, path: str) -> Optional[str]:
        """Detect LLM provider from request"""        
        for provider in self.providers.keys():
            if path.startswith(provider):
                return provider
        
        logger.error(f"Unsupported provider.")
        return None

    def detect_task_id(self, request: Request) -> Optional[str]:
        """Detect task ID from request for usage tracking"""
        task_id = request.headers.get("IWA-Task-ID", "")
        if task_id in self.allowed_task_ids:
            return task_id

        logger.error(f"Missing or invalid task ID for usage tracking.")
        return None

    def get_usage_for_task(self, task_id: str) -> LLMUsage:
        return self.usage_per_task.get(task_id, LLMUsage())
    
    def update_usage_for_task(self, provider: str, task_id: str, response_data: dict) -> None:
        """Update token usage for a specific task"""  
        usage = response_data.get("usage", {})

        input_tokens = usage.get("input_tokens", 10_000)
        output_tokens = usage.get("output_tokens", 10_000)
        total_tokens = input_tokens + output_tokens

        model = response_data.get("model", "")
        provider_config = self.providers[provider]
        pricing = provider_config.pricing.get(model, {})
        
        input_price = pricing.get("input", 10.0)
        output_price = pricing.get("output", 40.0)
        
        input_cost = (input_tokens / 1_000_000) * input_price
        output_cost = (output_tokens / 1_000_000) * output_price
        total_cost = input_cost + output_cost

        self.usage_per_task[task_id].add_usage(provider, model, total_tokens, total_cost)
        logger.info(f"Updated usage for task: {task_id}")
        logger.info(f"Provider: {provider} | Model: {model} | Tokens: {total_tokens} | Cost: {total_cost}")

    def set_allowed_task_ids(self, task_ids: Optional[list[str]] = None):
        """Set allowed task IDs for limiting other requests and tracking usage."""
        if task_ids is None:
            task_ids = []
        self.allowed_task_ids = set(task_ids)
        self.usage_per_task = {task_id: LLMUsage() for task_id in task_ids}
    
    def is_cost_exceeded(self, task_id: str) -> bool:
        return self.usage_per_task[task_id].total_cost >= COST_LIMIT_PER_TASK


# Initialize the gateway
gateway = LLMGateway()
app = FastAPI(
    title="Autoppia LLM Gateway", 
    description="Simple gateway for LLM requests with cost limiting"
)


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy"}


@app.get("/usage/{task_id}")
async def get_usage_for_task(task_id: str):
    """Get usage for a specific task ID"""
    usage = gateway.get_usage_for_task(task_id)
    return {
        "task_id": task_id,
        "total_tokens": usage.total_tokens,
        "total_cost": usage.total_cost,
        "usage_details": {
            "tokens": usage.tokens,
            "cost": usage.cost
        }
    }


@app.post("/set-allowed-task-ids")
async def set_allowed_task_ids(request: Request):
    """Set allowed task IDs for limiting other requests and tracking usage."""
    try:
        body = await request.json()
        task_ids = body.get("task_ids", [])
        gateway.set_allowed_task_ids(task_ids=task_ids)
    except Exception as e:
        logger.error(f"Error setting allowed task IDs: {e}")
        raise HTTPException(status_code=400, detail=f"Error setting allowed task IDs: {e}")
    return {"status": "allowed task IDs set"}


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def proxy_request(request: Request, path: str):
    """Main proxy endpoint for LLM requests"""
    try:
        # Detect provider
        provider = gateway.detect_provider(path)
        if not provider:
            raise HTTPException(status_code=400, detail="Unsupported provider!")

        # Detect task ID for usage tracking        
        task_id = gateway.detect_task_id(request)
        if not task_id:
            raise HTTPException(status_code=400, detail="Task ID not found!")
        
        if COST_LIMIT_ENABLED and gateway.is_cost_exceeded(task_id):
            current_usage = gateway.get_usage_for_task(task_id)
            raise HTTPException(
                status_code=402,
                detail=f"Cost limit exceeded. Current: ${current_usage.total_cost:.2f}, Limit: ${COST_LIMIT_PER_TASK:.2f}"
            )
        
        provider_config = gateway.providers[provider]
        url = f"{provider_config.base_url}{path.removeprefix(provider)}"
        
        # Forward the request
        headers = {}
        headers["Content-Type"] = "application/json"

        if provider == "openai" and OPENAI_API_KEY:
            headers["Authorization"] = f"Bearer {OPENAI_API_KEY}"

        if provider == "chutes" and CHUTES_API_KEY:
            headers["Authorization"] = f"Bearer {CHUTES_API_KEY}"

        body = await request.body()
        
        response = await gateway.http_client.request(
            method=request.method,
            url=url,
            headers=headers,
            params=request.query_params,
            content=body
        )
        
        # Parse response to extract usage and update tracking
        if response.status_code == 200:
            try:                      
                response_data = response.json()
                gateway.update_usage_for_task(provider, task_id, response_data)
            except (json.JSONDecodeError, ValueError):
                pass

        # Return response with cost headers
        response_headers = dict(response.headers)
        current_usage = gateway.get_usage_for_task(task_id)
        response_headers["X-Current-Cost"] = str(current_usage.total_cost)
        response_headers["X-Cost-Limit"] = str(COST_LIMIT_PER_TASK)
        
        return Response(
            content=response.content,
            status_code=response.status_code,
            headers=response_headers
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Gateway error: {str(e)}")
