# Autoppia Deployment Controller - Usage Guide

This guide explains how to use the Autoppia Deployment Controller to evaluate miner agents using their GitHub code instead of deployed endpoints.

## Overview

The deployment controller provides a complete blue/green deployment system with GitHub integration, designed specifically for evaluating web agents in the Autoppia subnet. Instead of calling deployed endpoints, validators can now deploy and test miner agents directly from their GitHub repositories.

## Quick Start

### 1. Setup

```bash
# Clone and setup
cd opensource
pip install -r requirements.txt

# Configure environment
cp env.example .env
# Edit .env with your settings

# Start with Docker Compose
docker-compose up -d
```

### 2. Basic Usage

```python
import asyncio
from example_usage import DeploymentControllerClient

async def main():
    client = DeploymentControllerClient(
        base_url="http://localhost:8000",
        auth_token="your-secret-token-here"
    )
    
    # Deploy a GitHub repository
    result = await client.create_deployment({
        "deployment_id": "my-app",
        "repo_url": "https://github.com/user/repo",
        "branch": "main",
        "health_path": "/health",
        "internal_port": 8000
    })
    
    print(f"Deployed: {result}")

asyncio.run(main())
```

## API Endpoints

### Core Deployment Endpoints

#### Create Deployment
```http
POST /v1/repos
Authorization: Bearer <token>
Content-Type: application/json

{
  "deployment_id": "my-app",
  "repo_url": "https://github.com/user/repo",
  "branch": "main",
  "health_path": "/health",
  "internal_port": 8000,
  "env": ["NODE_ENV=production"],
  "build_args": ["BUILD_ENV=prod"]
}
```

#### Get Deployment Status
```http
GET /v1/repos/{deployment_id}
Authorization: Bearer <token>
```

#### Redeploy
```http
POST /v1/repos/{deployment_id}/redeploy
Authorization: Bearer <token>
Content-Type: application/json

{
  "branch": "feature/new-feature",
  "env": ["FEATURE_FLAG=new-feature"]
}
```

#### Switch Blue/Green
```http
POST /v1/repos/{deployment_id}/switch
Authorization: Bearer <token>
Content-Type: application/json

{
  "color": "green",
  "force": false
}
```

#### Delete Deployment
```http
DELETE /v1/repos/{deployment_id}?keep_images=false
Authorization: Bearer <token>
```

### Validator Integration Endpoints

#### Evaluate Single Miner
```http
POST /v1/integration/evaluate-miner
Authorization: Bearer <token>
Content-Type: application/json

{
  "github_url": "https://github.com/miner/agent",
  "branch": "main",
  "task_prompt": "Navigate to homepage and click login",
  "task_url": "https://example.com"
}
```

#### Batch Evaluate Miners
```http
POST /v1/integration/evaluate-miners-batch
Authorization: Bearer <token>
Content-Type: application/json

{
  "miners": [
    {
      "github_url": "https://github.com/miner1/agent",
      "branch": "main",
      "task_prompt": "Click search button",
      "task_url": "https://example.com"
    },
    {
      "github_url": "https://github.com/miner2/agent",
      "branch": "dev",
      "task_prompt": "Fill contact form",
      "task_url": "https://example.com"
    }
  ]
}
```

## Integration with Validator

### How It Works

1. **Validator generates tasks** using the existing IWA system
2. **Instead of calling deployed endpoints**, the validator uses the deployment controller
3. **Deployment controller**:
   - Clones the miner's GitHub repository
   - Builds and deploys the agent in a container
   - Sends evaluation tasks to the deployed agent
   - Collects results and returns them to the validator
   - Cleans up the deployment

### Example Validator Integration

```python
# In your validator.py
from opensource.validator_integration import ValidatorIntegration

class Validator(BaseValidatorNeuron):
    def __init__(self, config=None):
        super().__init__(config=config)
        # Initialize deployment controller integration
        self.deployment_controller = DeploymentController()
        self.validator_integration = ValidatorIntegration(
            self.deployment_controller
        )
    
    async def evaluate_miner_from_github(self, miner_github_url: str, task: Task):
        """Evaluate a miner using their GitHub code."""
        result = await self.validator_integration.evaluate_miner_from_github(
            miner_github_url=miner_github_url,
            miner_branch="main",
            task_prompt=task.prompt,
            task_url=task.url
        )
        
        # Convert to validator-compatible format
        return {
            "success": result["success"],
            "execution_time": result["execution_time"],
            "actions_count": result["actions_count"],
            "error": result.get("error")
        }
```

## Blue/Green Deployment Workflow

### 1. Initial Deployment (Blue)
```python
# Deploy to blue
deployment = await client.create_deployment({
    "deployment_id": "my-app",
    "repo_url": "https://github.com/user/repo",
    "branch": "main"
})
```

### 2. Deploy New Version (Green)
```python
# Redeploy to green with new branch
await client.redeploy("my-app", {
    "branch": "feature/new-feature"
})
```

### 3. Health Check and Promote
```python
# Check if green is healthy
status = await client.get_deployment_status("my-app")
if status["data"]["overall_health"] == "healthy":
    # Promote green to active
    await client.switch_deployment("my-app", "green")
```

### 4. Rollback if Needed
```python
# Rollback to blue
await client.switch_deployment("my-app", "blue")
```

## Configuration

### Environment Variables

```bash
# Authentication
AUTH_TOKEN=your-secret-token-here

# Docker Configuration
DOCKER_NETWORK=deployer_network

# Port Management
PORT_POOL_START=40000
PORT_POOL_END=41000

# Health Check Configuration
DEFAULT_PROBE_TIMEOUT=120
DEFAULT_GRACE_PERIOD=60

# Rate Limiting
MAX_CONCURRENT_BUILDS=3
RATE_LIMIT_REQUESTS=100
RATE_LIMIT_WINDOW=3600

# Storage
STATE_DIR=/srv/deployer/state
WORK_DIR=/srv/deployer/work
LOGS_DIR=/srv/deployer/logs
```

### Docker Compose

The system includes a complete Docker Compose setup with:
- **Traefik**: Reverse proxy for dynamic routing
- **Deployment Controller**: Main API service
- **Shared Network**: For container communication

## Security Features

- **Authentication**: Bearer token authentication
- **Rate Limiting**: Configurable request rate limits
- **IP Whitelisting**: Optional IP address restrictions
- **Input Validation**: Sanitized environment variables and build args
- **Resource Limits**: CPU and memory limits for containers
- **Non-root Containers**: All containers run as non-root user

## Monitoring and Logging

### Health Checks
```http
GET /v1/healthz
```

### Deployment Status
```http
GET /v1/status
```

### Container Logs
```http
GET /v1/repos/{deployment_id}/logs?color=blue&tail=200
```

### Structured Logging
All operations are logged with structured JSON format including:
- Request IDs for tracing
- Deployment IDs for correlation
- Operation types and status
- Error details and stack traces

## Troubleshooting

### Common Issues

1. **Docker not available**
   - Ensure Docker daemon is running
   - Check Docker socket permissions

2. **Traefik not accessible**
   - Verify Traefik container is running
   - Check network connectivity

3. **Port allocation failed**
   - Increase port pool range
   - Check for port conflicts

4. **Health check failures**
   - Verify health endpoint exists
   - Check container logs
   - Adjust probe timeout

### Debug Mode

```bash
# Enable debug logging
export LOG_LEVEL=DEBUG
python main.py
```

### Container Debugging

```bash
# Check container status
docker ps -a

# View container logs
docker logs <container_id>

# Inspect container
docker inspect <container_id>
```

## Performance Considerations

- **Concurrent Builds**: Limited by `MAX_CONCURRENT_BUILDS`
- **Port Pool**: Manages port allocation efficiently
- **Image Cleanup**: Automatic cleanup of old images
- **Resource Limits**: CPU and memory limits per container
- **Health Check Intervals**: Configurable probe intervals

## Production Deployment

### Security Checklist

- [ ] Change default AUTH_TOKEN
- [ ] Configure IP whitelist
- [ ] Set up TLS termination
- [ ] Configure resource limits
- [ ] Set up monitoring and alerting
- [ ] Regular security updates

### Scaling Considerations

- **Horizontal Scaling**: Multiple controller instances
- **Load Balancing**: Traefik handles load balancing
- **State Management**: Consider external database for state
- **Image Registry**: Use private registry for images

## Examples

See `example_usage.py` for comprehensive examples including:
- Basic deployment workflows
- Blue/green deployment patterns
- Miner evaluation workflows
- Validator integration examples

Run examples:
```bash
python example_usage.py
```
