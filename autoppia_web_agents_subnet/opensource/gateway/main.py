import os
import json
import time
import logging
from typing import Optional

import httpx
from fastapi import FastAPI, Request, HTTPException, Response

from models import TokenUsage, ProviderConfig, DEFAULT_PROVIDER_CONFIGS
from config import (
    COST_LIMIT_ENABLED,
    COST_LIMIT_VALUE,
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
        self.current_usage = TokenUsage() 
    
    def detect_provider(self, request: Request) -> Optional[str]:
        """Detect LLM provider from request"""
        host = request.headers.get("host", "")
        
        for provider in self.providers.keys():
            if provider in host:
                return provider
        
        logger.error(f"Unsupported provider.")
        return None

    def get_current_usage(self) -> float:
        return self.current_usage
    
    def update_usage(self, provider: str, response_data: dict) -> None:
        """Update token usage"""  
        usage = response_data.get("usage", {})

        input_tokens = usage.get("input_tokens", 10_000)
        output_tokens = usage.get("output_tokens", 10_000)
        self.current_usage.total_tokens += input_tokens + output_tokens

        logger.info(f"Used {input_tokens} input tokens, {output_tokens} output tokens")
        logger.info(f"Total token usage: {self.current_usage.total_tokens}.")

        model = response_data.get("model", "")
        provider_config = self.providers[provider]
        pricing = provider_config.pricing.get(model, {})
        
        input_price = pricing.get("input", 10.0)
        output_price = pricing.get("output", 40.0)
        
        input_cost = (input_tokens / 1_000_000) * input_price
        output_cost = (output_tokens / 1_000_000) * output_price
        self.current_usage.total_cost += input_cost + output_cost

        logger.info(f"Used ${input_cost:.4f} input, ${output_cost:.4f} output")
        logger.info(f"Total cost usage: ${self.current_usage.total_cost:.4f}.")

    def reset_usage(self) -> None:
        self.current_usage = TokenUsage()    
    
    def is_cost_exceeded(self) -> bool:
        return self.current_usage.total_cost >= COST_LIMIT_VALUE


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


@app.get("/usage")
async def get_usage():
    """Get current usage statistics"""
    current_usage = gateway.get_current_usage()
    return {
        "total_tokens": current_usage.total_tokens,
        "total_cost": current_usage.total_cost
    }


@app.post("/reset")
async def reset_usage():
    """Reset current usage for new agent evaluation"""
    gateway.reset_usage()
    return {"status": "reset", "message": "Usage has been reset for new evaluation"}


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def proxy_request(request: Request, path: str):
    """Main proxy endpoint for LLM requests"""
    try:
        # Detect provider
        provider = gateway.detect_provider(request)
        if not provider:
            raise HTTPException(status_code=400, detail="Unsupported provider!")
        
        if COST_LIMIT_ENABLED and gateway.is_cost_exceeded():
            current_usage = gateway.get_current_usage()
            raise HTTPException(
                status_code=402,
                detail=f"Cost limit exceeded. Current: ${current_usage.total_cost:.2f}, Limit: ${COST_LIMIT_VALUE:.2f}"
            )
        
        provider_config = gateway.providers[provider]
        url = f"{provider_config.base_url}/{path}"
        
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
                gateway.update_usage(provider, response_data)
            except (json.JSONDecodeError, ValueError):
                pass

        # Return response with cost headers
        response_headers = dict(response.headers)
        current_usage = gateway.get_current_usage()
        response_headers["X-Current-Cost"] = str(current_usage.total_cost)
        response_headers["X-Cost-Limit"] = str(COST_LIMIT_VALUE)
        
        return Response(
            content=response.content,
            status_code=response.status_code,
            headers=response_headers
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Gateway error: {str(e)}")
