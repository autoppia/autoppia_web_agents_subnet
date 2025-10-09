"""
Security features for the deployment controller.
"""
import asyncio
import time
from collections import defaultdict, deque
from typing import Dict, List, Optional, Set
from ipaddress import ip_address, ip_network

import structlog
from fastapi import Request, HTTPException, status

logger = structlog.get_logger(__name__)


class RateLimiter:
    """Rate limiter for API endpoints."""

    def __init__(self, max_requests: int = 100, window_seconds: int = 3600):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.requests: Dict[str, deque] = defaultdict(deque)
        self._cleanup_task: Optional[asyncio.Task] = None

    def _get_client_id(self, request: Request) -> str:
        """Get client identifier for rate limiting."""
        # Try to get real IP from headers (for reverse proxy setups)
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()

        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip

        # Fall back to direct client IP
        return request.client.host if request.client else "unknown"

    def is_allowed(self, request: Request) -> bool:
        """Check if request is allowed under rate limit."""
        client_id = self._get_client_id(request)
        now = time.time()

        # Clean old requests
        client_requests = self.requests[client_id]
        while client_requests and client_requests[0] <= now - self.window_seconds:
            client_requests.popleft()

        # Check if under limit
        if len(client_requests) >= self.max_requests:
            return False

        # Add current request
        client_requests.append(now)
        return True

    def get_remaining_requests(self, request: Request) -> int:
        """Get remaining requests for client."""
        client_id = self._get_client_id(request)
        now = time.time()

        # Clean old requests
        client_requests = self.requests[client_id]
        while client_requests and client_requests[0] <= now - self.window_seconds:
            client_requests.popleft()

        return max(0, self.max_requests - len(client_requests))

    def get_reset_time(self, request: Request) -> float:
        """Get time when rate limit resets."""
        client_id = self._get_client_id(request)
        client_requests = self.requests[client_id]

        if not client_requests:
            return time.time()

        return client_requests[0] + self.window_seconds

    async def start_cleanup_task(self):
        """Start background cleanup task."""
        if self._cleanup_task is None:
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    async def stop_cleanup_task(self):
        """Stop background cleanup task."""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self._cleanup_task = None

    async def _cleanup_loop(self):
        """Background cleanup of old requests."""
        while True:
            try:
                await asyncio.sleep(300)  # Clean up every 5 minutes
                now = time.time()

                for client_id in list(self.requests.keys()):
                    client_requests = self.requests[client_id]
                    while client_requests and client_requests[0] <= now - self.window_seconds:
                        client_requests.popleft()

                    # Remove empty entries
                    if not client_requests:
                        del self.requests[client_id]

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Rate limiter cleanup error", error=str(e))


class IPWhitelist:
    """IP address whitelist for access control."""

    def __init__(self, allowed_ips: Optional[List[str]] = None):
        self.allowed_networks: List[ip_network] = []

        if allowed_ips:
            for ip_str in allowed_ips:
                try:
                    if "/" in ip_str:
                        # CIDR notation
                        self.allowed_networks.append(ip_network(ip_str))
                    else:
                        # Single IP
                        self.allowed_networks.append(ip_network(f"{ip_str}/32"))
                except ValueError as e:
                    logger.warning("Invalid IP address in whitelist", ip=ip_str, error=str(e))

    def is_allowed(self, request: Request) -> bool:
        """Check if client IP is allowed."""
        if not self.allowed_networks:
            return True  # No restrictions if no whitelist

        client_ip = self._get_client_ip(request)
        if not client_ip:
            return False

        try:
            client_addr = ip_address(client_ip)
            return any(client_addr in network for network in self.allowed_networks)
        except ValueError:
            return False

    def _get_client_ip(self, request: Request) -> Optional[str]:
        """Get client IP address."""
        # Try to get real IP from headers (for reverse proxy setups)
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()

        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip

        # Fall back to direct client IP
        return request.client.host if request.client else None


class SecurityManager:
    """Centralized security management."""

    def __init__(self, 
                 rate_limit_requests: int = 100,
                 rate_limit_window: int = 3600,
                 allowed_ips: Optional[List[str]] = None,
                 max_concurrent_builds: int = 3):

        self.rate_limiter = RateLimiter(rate_limit_requests, rate_limit_window)
        self.ip_whitelist = IPWhitelist(allowed_ips)
        self.max_concurrent_builds = max_concurrent_builds
        self.active_builds: Set[str] = set()
        self.build_lock = asyncio.Lock()

    async def initialize(self):
        """Initialize security manager."""
        await self.rate_limiter.start_cleanup_task()
        logger.info("Security manager initialized")

    async def shutdown(self):
        """Shutdown security manager."""
        await self.rate_limiter.stop_cleanup_task()
        logger.info("Security manager shutdown")

    def check_rate_limit(self, request: Request) -> bool:
        """Check if request is within rate limits."""
        return self.rate_limiter.is_allowed(request)

    def check_ip_whitelist(self, request: Request) -> bool:
        """Check if client IP is whitelisted."""
        return self.ip_whitelist.is_allowed(request)

    def get_rate_limit_headers(self, request: Request) -> Dict[str, str]:
        """Get rate limit headers for response."""
        remaining = self.rate_limiter.get_remaining_requests(request)
        reset_time = self.rate_limiter.get_reset_time(request)

        return {
            "X-RateLimit-Limit": str(self.rate_limiter.max_requests),
            "X-RateLimit-Remaining": str(remaining),
            "X-RateLimit-Reset": str(int(reset_time))
        }

    async def acquire_build_slot(self, deployment_id: str) -> bool:
        """Acquire a build slot for concurrent build limiting."""
        async with self.build_lock:
            if len(self.active_builds) >= self.max_concurrent_builds:
                return False

            self.active_builds.add(deployment_id)
            logger.info("Acquired build slot", 
                        deployment_id=deployment_id, 
                        active_builds=len(self.active_builds))
            return True

    async def release_build_slot(self, deployment_id: str):
        """Release a build slot."""
        async with self.build_lock:
            self.active_builds.discard(deployment_id)
            logger.info("Released build slot", 
                        deployment_id=deployment_id, 
                        active_builds=len(self.active_builds))

    def validate_repo_url(self, repo_url: str) -> bool:
        """Validate repository URL for security."""
        # Only allow HTTPS GitHub URLs
        if not repo_url.startswith("https://github.com/"):
            return False

        # Check for suspicious patterns
        suspicious_patterns = [
            "..",  # Path traversal
            "~",   # Home directory
            "//",  # Double slashes
            "\\",  # Backslashes
        ]

        for pattern in suspicious_patterns:
            if pattern in repo_url:
                return False

        return True

    def sanitize_env_vars(self, env_vars: List[str]) -> List[str]:
        """Sanitize environment variables."""
        sanitized = []

        for env_var in env_vars:
            if "=" not in env_var:
                continue

            key, value = env_var.split("=", 1)

            # Remove potentially dangerous environment variables
            dangerous_vars = {
                "PATH", "LD_LIBRARY_PATH", "PYTHONPATH", "NODE_PATH",
                "HOME", "USER", "SHELL", "TERM", "TMPDIR", "TMP", "TEMP"
            }

            if key.upper() in dangerous_vars:
                logger.warning("Blocked dangerous environment variable", key=key)
                continue

            # Limit value length
            if len(value) > 1000:
                logger.warning("Truncated long environment variable", key=key)
                value = value[:1000]

            sanitized.append(f"{key}={value}")

        return sanitized

    def sanitize_build_args(self, build_args: List[str]) -> List[str]:
        """Sanitize build arguments."""
        sanitized = []

        for arg in build_args:
            if "=" not in arg:
                continue

            key, value = arg.split("=", 1)

            # Block potentially dangerous build args
            dangerous_args = {
                "BUILDKIT_INLINE_CACHE", "DOCKER_BUILDKIT", "BUILDX_NO_DEFAULT_ATTESTATIONS"
            }

            if key.upper() in dangerous_args:
                logger.warning("Blocked dangerous build argument", key=key)
                continue

            # Limit value length
            if len(value) > 1000:
                logger.warning("Truncated long build argument", key=key)
                value = value[:1000]

            sanitized.append(f"{key}={value}")

        return sanitized


def create_security_exception(message: str, status_code: int = status.HTTP_403_FORBIDDEN) -> HTTPException:
    """Create a security-related HTTP exception."""
    return HTTPException(
        status_code=status_code,
        detail=message,
        headers={"X-Security-Reason": message}
    )
