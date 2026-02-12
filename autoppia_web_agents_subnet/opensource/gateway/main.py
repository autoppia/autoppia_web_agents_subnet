import asyncio
import json
import logging
import time
from typing import Optional

import httpx
from fastapi import FastAPI, Request, HTTPException, Response
import secrets

from models import LLMUsage, DEFAULT_PROVIDER_CONFIGS
from config import (
    COST_LIMIT_ENABLED,
    COST_LIMIT_PER_TASK,
    OPENAI_API_KEY,
    CHUTES_API_KEY,
    SANDBOX_GATEWAY_ADMIN_TOKEN,
    OPENAI_ALLOWED_MODELS,
    CHUTES_ALLOWED_MODELS,
    OPENAI_ALLOWED_PATHS,
    CHUTES_ALLOWED_PATHS,
    GATEWAY_STRICT_PRICING,
    CHUTES_PRICING_TTL_SECONDS,
    CHUTES_PRICING_TIMEOUT_SECONDS,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("/app/logs/gateway.log"),    
        logging.StreamHandler()             
    ]
)
logger = logging.getLogger(__name__)


class LLMGateway:
    """Simplified gateway for single agent evaluation"""
    
    def __init__(self): 
        self.providers = DEFAULT_PROVIDER_CONFIGS.copy()
        self.http_client = httpx.AsyncClient(timeout=60.0)
        self.allowed_task_ids = set()
        self.usage_per_task: dict[str, LLMUsage] = {}
        self._chutes_pricing_lock = asyncio.Lock()
        self._chutes_pricing_last_refresh = 0.0
    
    def detect_provider(self, path: str) -> Optional[str]:
        """Detect LLM provider from request"""        
        for provider in self.providers.keys():
            # Require an exact provider match or a slash-delimited prefix.
            # This prevents SSRF-style host override via paths like "openai@evil.com/...".
            if path == provider or path.startswith(f"{provider}/"):
                return provider
        
        logger.error(f"Unsupported provider.")
        return None

    def detect_task_id(self, request: Request) -> Optional[str]:
        """Detect task ID from request for usage tracking"""
        task_id = request.headers.get("iwa-task-id", "")
        if task_id in self.allowed_task_ids:
            return task_id

        logger.error(f"Missing or invalid task ID for usage tracking.")
        logger.error(f"Task ID: {task_id}")
        return None

    def get_usage_for_task(self, task_id: str) -> LLMUsage:
        return self.usage_per_task.get(task_id, LLMUsage())

    def _is_allowed_path(self, provider: str, suffix: str) -> bool:
        allowed = OPENAI_ALLOWED_PATHS if provider == "openai" else CHUTES_ALLOWED_PATHS if provider == "chutes" else set()
        if not allowed:
            return True
        for p in allowed:
            if suffix == p or suffix.startswith(p + "/"):
                return True
        return False

    def _is_allowed_model(self, provider: str, model: str) -> bool:
        allowed = OPENAI_ALLOWED_MODELS if provider == "openai" else CHUTES_ALLOWED_MODELS if provider == "chutes" else set()
        if not allowed:
            return True
        return model in allowed

    def _resolve_pricing_model(self, provider: str, model: str) -> str:
        """
        Resolve a request/response model id to a priced model key.

        OpenAI (and some OpenAI-compatible providers) may return or accept versioned
        model ids like "gpt-4o-2024-08-06". We price these by longest-prefix match
        against our known pricing keys (e.g. "gpt-4o").
        """
        provider_config = self.providers.get(provider)
        if not provider_config or not model:
            return model
        if model in provider_config.pricing:
            return model
        best_key = ""
        for key in provider_config.pricing.keys():
            if model.startswith(key) and len(key) > len(best_key):
                best_key = key
        return best_key or model

    async def refresh_chutes_pricing(self) -> bool:
        """
        Fetch Chutes model pricing from the public OpenAI-compatible models endpoint.

        Expected schema (subset):
          GET https://llm.chutes.ai/v1/models
          {
            "data": [
              {"id": "...", "price": {"input": {"usd": 0.1}, "output": {"usd": 0.3}, "input_cache_read": {"usd": 0.05}}},
              {"id": "...", "pricing": {"prompt": 0.1, "completion": 0.3, "input_cache_read": 0.05}}
            ]
          }
        """
        provider_config = self.providers.get("chutes")
        if not provider_config:
            return False

        url = str(httpx.URL(provider_config.base_url).copy_with(path="/v1/models"))
        headers = {"Accept": "application/json"}
        if CHUTES_API_KEY:
            headers["Authorization"] = f"Bearer {CHUTES_API_KEY}"

        try:
            resp = await self.http_client.get(url, headers=headers, timeout=CHUTES_PRICING_TIMEOUT_SECONDS)
            resp.raise_for_status()
            payload = resp.json() or {}
            models = payload.get("data") or []
        except Exception as e:
            logger.warning(f"Failed to fetch Chutes pricing from {url}: {e}")
            return False

        pricing_map: dict[str, dict[str, float]] = {}
        for m in models:
            if not isinstance(m, dict):
                continue
            mid = str(m.get("id") or "")
            if not mid:
                continue

            entry: dict[str, float] = {}

            # Preferred: structured "price" with USD.
            price = m.get("price")
            if isinstance(price, dict):
                try:
                    in_usd = ((price.get("input") or {}).get("usd"))
                    out_usd = ((price.get("output") or {}).get("usd"))
                    cache_usd = ((price.get("input_cache_read") or {}).get("usd"))
                    if in_usd is not None:
                        entry["input"] = float(in_usd)
                    if out_usd is not None:
                        entry["output"] = float(out_usd)
                    if cache_usd is not None:
                        entry["input_cache_read"] = float(cache_usd)
                except Exception:
                    entry = {}

            # Fallback: flat "pricing" (prompt/completion) in USD per 1M tokens.
            if not entry:
                pricing = m.get("pricing")
                if isinstance(pricing, dict):
                    try:
                        if pricing.get("input") is not None:
                            entry["input"] = float(pricing["input"])
                        if pricing.get("output") is not None:
                            entry["output"] = float(pricing["output"])
                        if pricing.get("prompt") is not None:
                            entry["input"] = float(pricing["prompt"])
                        if pricing.get("completion") is not None:
                            entry["output"] = float(pricing["completion"])
                        if pricing.get("input_cache_read") is not None:
                            entry["input_cache_read"] = float(pricing["input_cache_read"])
                    except Exception:
                        entry = {}

            if "input" in entry and "output" in entry:
                pricing_map[mid] = entry

        if pricing_map:
            provider_config.pricing = pricing_map
            self._chutes_pricing_last_refresh = time.time()
            logger.info(f"Loaded Chutes pricing for {len(pricing_map)} models")
            return True

        logger.warning("Chutes /v1/models returned no models with usable pricing")
        return False

    async def ensure_provider_pricing(self, provider: str) -> None:
        if provider != "chutes":
            return

        now = time.time()
        if self._chutes_pricing_last_refresh and (now - self._chutes_pricing_last_refresh) < CHUTES_PRICING_TTL_SECONDS:
            return

        async with self._chutes_pricing_lock:
            now = time.time()
            if self._chutes_pricing_last_refresh and (now - self._chutes_pricing_last_refresh) < CHUTES_PRICING_TTL_SECONDS:
                return
            # Refresh best-effort.
            await self.refresh_chutes_pricing()
    
    def update_usage_for_task(self, provider: str, task_id: str, response_data: dict) -> None:
        """Update token usage for a specific task""" 
        usage = response_data.get("usage") or {}

        # Support both OpenAI-style {prompt_tokens, completion_tokens} and
        # Responses API-style {input_tokens, output_tokens}.
        input_tokens = usage.get("input_tokens")
        output_tokens = usage.get("output_tokens")
        if input_tokens is None and output_tokens is None:
            input_tokens = usage.get("prompt_tokens")
            output_tokens = usage.get("completion_tokens")
        if input_tokens is None and output_tokens is None:
            total = usage.get("total_tokens")
            if total is not None:
                input_tokens, output_tokens = total, 0
            else:
                input_tokens, output_tokens = 0, 0
                logger.warning(f"Missing usage in provider response (provider={provider}, task_id={task_id}).")

        input_tokens = int(input_tokens or 0)
        output_tokens = int(output_tokens or 0)
        total_tokens = input_tokens + output_tokens

        cached_input_tokens = 0
        try:
            details = usage.get("input_tokens_details") or usage.get("prompt_tokens_details") or {}
            if isinstance(details, dict):
                cached_input_tokens = int(details.get("cached_tokens") or details.get("cache_read_tokens") or 0)
        except Exception:
            cached_input_tokens = 0
        if cached_input_tokens < 0:
            cached_input_tokens = 0
        if cached_input_tokens > input_tokens:
            cached_input_tokens = input_tokens

        model = str(response_data.get("model", "") or "")
        provider_config = self.providers[provider]
        pricing_model = self._resolve_pricing_model(provider, model)
        pricing = provider_config.pricing.get(pricing_model, {})
        
        input_price = float(pricing.get("input", provider_config.default_input_price))
        cached_input_price = float(pricing.get("input_cache_read", input_price))
        output_price = float(pricing.get("output", provider_config.default_output_price))
        
        non_cached_input_tokens = max(0, input_tokens - cached_input_tokens)
        input_cost = (non_cached_input_tokens / 1_000_000) * input_price
        cached_input_cost = (cached_input_tokens / 1_000_000) * cached_input_price
        output_cost = (output_tokens / 1_000_000) * output_price
        total_cost = input_cost + cached_input_cost + output_cost

        self.usage_per_task[task_id].add_usage(provider, model, total_tokens, total_cost)
        logger.info(f"Updated usage for task: {task_id}")
        if pricing_model and pricing_model != model:
            logger.info(f"Provider: {provider} | Model: {model} (priced_as={pricing_model}) | Tokens: {total_tokens} | Cost: {total_cost}")
        else:
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

@app.on_event("startup")
async def _startup() -> None:
    # Best-effort: populate Chutes pricing so strict pricing works immediately.
    try:
        await gateway.refresh_chutes_pricing()
    except Exception:
        pass

def _require_admin(request: Request) -> None:
    if not SANDBOX_GATEWAY_ADMIN_TOKEN:
        raise HTTPException(status_code=500, detail="Gateway admin token not configured")
    token = request.headers.get("x-admin-token", "")
    if not secrets.compare_digest(token, SANDBOX_GATEWAY_ADMIN_TOKEN):
        raise HTTPException(status_code=403, detail="Forbidden")


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy"}


@app.get("/usage/{task_id}")
async def get_usage_for_task(task_id: str, request: Request):
    """Get usage for a specific task ID"""
    # Usage is validator-only. Prevent miners from probing cost state.
    _require_admin(request)
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
    _require_admin(request)
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
        suffix = path.removeprefix(provider)
        if suffix and not suffix.startswith("/"):
            raise HTTPException(status_code=400, detail="Invalid provider path")
        if not suffix:
            raise HTTPException(status_code=400, detail="Missing provider path")

        if not gateway._is_allowed_path(provider, suffix):
            raise HTTPException(status_code=400, detail="Unsupported endpoint")

        # Ensure pricing is loaded (Chutes) before we validate model/price.
        await gateway.ensure_provider_pricing(provider)

        # Build upstream URL ensuring the scheme/host always come from the trusted provider config.
        # This prevents authority-section injection like "https://api.openai.com@evil.com/..." .
        base = httpx.URL(provider_config.base_url)
        url = str(base.copy_with(raw_path=suffix.encode("utf-8") if suffix else b""))
        
        # Forward the request
        headers = {}
        headers["Content-Type"] = "application/json"

        if provider == "openai" and OPENAI_API_KEY:
            headers["Authorization"] = f"Bearer {OPENAI_API_KEY}"

        if provider == "chutes" and CHUTES_API_KEY:
            headers["Authorization"] = f"Bearer {CHUTES_API_KEY}"

        body = await request.body()
        parsed_body = None
        try:
            if body and request.headers.get("content-type", "").startswith("application/json"):
                parsed_body = json.loads(body.decode("utf-8"))
                # Disallow streaming: usage accounting (and cost limiting) relies on a
                # usage object in the final JSON response.
                if isinstance(parsed_body, dict) and parsed_body.get("stream") is True:
                    raise HTTPException(status_code=400, detail="Streaming is not supported")
        except UnicodeDecodeError:
            pass
        except json.JSONDecodeError:
            pass

        # Enforce per-provider model allowlist and (optionally) strict pricing.
        if request.method in ("POST", "PUT", "PATCH") and isinstance(parsed_body, dict):
            model = str(parsed_body.get("model") or "")
            if not model:
                raise HTTPException(status_code=400, detail="Missing model")
            if not gateway._is_allowed_model(provider, model):
                raise HTTPException(status_code=400, detail="Model not allowed")
            if GATEWAY_STRICT_PRICING:
                pricing_model = gateway._resolve_pricing_model(provider, model)
                # If Chutes pricing fetch fails (e.g. transient outage), fall back to
                # conservative defaults rather than hard-fail the task.
                if (provider != "chutes" or provider_config.pricing) and pricing_model not in provider_config.pricing:
                    raise HTTPException(status_code=400, detail="Missing pricing for model")
        
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
