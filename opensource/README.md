 Autoppia Deployment Controller

A deployment controller API that builds & runs GitHub repos in Docker, performs blue/green health-gated swaps, and exposes endpoints for deployment management. Designed to evaluate miner agents using their GitHub code instead of deployed endpoints.

## Architecture

- **Controller API** (FastAPI): Manages deployment state machine and blue/green swap logic
- **Docker Integration**: Builds and runs containers from GitHub repositories
- **Traefik Proxy**: Routes traffic to blue/green containers dynamically
- **State Management**: Persists deployment records and manages port allocation
- **Health Checks**: Validates container health before promoting deployments

## Features

- Blue/green deployments with health-gated swaps
- GitHub repository integration
- Docker container management
- Dynamic routing with Traefik
- RESTful API for deployment operations
- Authentication and rate limiting
- Comprehensive logging and monitoring

## Quick Start

1. Install dependencies: `pip install -r requirements.txt`
2. Configure environment variables in `.env`
3. Start Traefik: `docker-compose up -d traefik`
4. Start the controller: `python main.py`

## API Endpoints

- `GET /v1/status` - List all deployments
- `POST /v1/repos` - Create or deploy a repository
- `POST /v1/repos/{deployment_id}/redeploy` - Redeploy with updates
- `POST /v1/repos/{deployment_id}/switch` - Switch between blue/green
- `DELETE /v1/repos/{deployment_id}` - Delete deployment
- `GET /v1/repos/{deployment_id}/logs` - Get container logs
- `GET /v1/healthz` - Controller health check

## Integration with Validator

This controller integrates with the Autoppia validator to evaluate miner agents using their GitHub code instead of deployed endpoints, enabling more flexible and comprehensive agent testing.

## Miner Repository Standard

Miners must structure their GitHub repositories according to the [Autoppia Miner Repository Standard](MINER_REPOSITORY_STANDARD.md) to be compatible with the deployment controller. The standard requires:

- **docker-compose.yml** - Main deployment configuration
- **agent/** directory with Dockerfile, main.py, and requirements.txt
- **FastAPI endpoints** - /health, /api/task, /api/info
- **Port 8000** - Must expose port 8000 for the agent service
- **Health checks** - Built-in health monitoring
- **README.md** - Documentation following standard format

See the [example template](examples/miner-template/) for a complete reference implementation.

## Validation

Use the validation endpoints to check if your repository follows the standard:

```bash
# Validate a repository
curl -X POST http://localhost:8000/v1/validation/repository \
  -H "Content-Type: application/json" \
  -d '{"github_url": "https://github.com/user/miner-agent", "branch": "main"}'

# Get validation standard
curl http://localhost:8000/v1/validation/standard

# Get repository template
curl http://localhost:8000/v1/validation/template
```
