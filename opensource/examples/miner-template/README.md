# Autoppia Miner Agent Template

This is a template repository that follows the Autoppia Miner Repository Standard. Use this as a starting point for your own miner agent implementation.

## Description

This template provides a basic web agent implementation that can:
- Navigate to web pages
- Click on elements
- Fill out forms
- Take screenshots
- Extract text content

## Features

- **Web Navigation**: Navigate to any URL
- **Element Interaction**: Click buttons, links, and other interactive elements
- **Form Filling**: Fill out forms with appropriate data
- **Screenshot Capture**: Take screenshots of web pages
- **Text Extraction**: Extract text content from web elements
- **Health Monitoring**: Built-in health check endpoint
- **Structured Logging**: Comprehensive logging with Loguru

## Quick Start

### Local Development

```bash
# Clone this template
git clone <your-repo-url>
cd <your-repo>

# Start with docker-compose
docker-compose up -d

# Check health
curl http://localhost:8000/health

# Test with a sample task
curl -X POST http://localhost:8000/api/task \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "Navigate to the homepage and click the login button",
    "url": "https://example.com",
    "version": "1.0.0"
  }'
```

### Environment Variables

Configure your agent with these environment variables:

```bash
# Required
AGENT_NAME="My Custom Agent"
AGENT_VERSION="1.0.0"
GITHUB_URL="https://github.com/your-username/your-repo"

# Optional
HAS_RL="false"  # Set to "true" if using reinforcement learning
LOG_LEVEL="INFO"  # DEBUG, INFO, WARNING, ERROR
```

## API Endpoints

### Health Check
```http
GET /health
```

Response:
```json
{
  "status": "healthy",
  "agent_name": "My Custom Agent",
  "version": "1.0.0",
  "timestamp": 1234567890.123
}
```

### Process Task
```http
POST /api/task
Content-Type: application/json

{
  "prompt": "Navigate to the homepage and click the login button",
  "url": "https://example.com",
  "html": "<html>...</html>",
  "screenshot": "base64-encoded-image",
  "actions": [],
  "version": "1.0.0"
}
```

Response:
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

### Agent Information
```http
GET /api/info
```

Response:
```json
{
  "agent_name": "My Custom Agent",
  "version": "1.0.0",
  "capabilities": [
    "web_navigation",
    "element_interaction",
    "form_filling",
    "screenshot_capture",
    "text_extraction"
  ],
  "github_url": "https://github.com/your-username/your-repo",
  "has_rl": false
}
```

## Customization

### 1. Implement Your Agent Logic

Replace the example logic in `agent/main.py` with your own implementation:

```python
async def solve_task(self, prompt: str, url: str, html: str = "", screenshot: str = "") -> List[Dict[str, Any]]:
    """
    Implement your web agent logic here.
    
    Args:
        prompt: Task description from validator
        url: Target URL
        html: Current page HTML (optional)
        screenshot: Current page screenshot (optional)
    
    Returns:
        List of actions to perform
    """
    # Your implementation here
    actions = []
    
    # Example: Use Selenium, Playwright, or other tools
    # to interact with the web page based on the prompt
    
    return actions
```

### 2. Add Dependencies

Update `agent/requirements.txt` with your dependencies:

```txt
fastapi==0.104.1
uvicorn[standard]==0.24.0
pydantic==2.5.0
selenium==4.15.0
playwright==1.40.0
# Add your dependencies here
```

### 3. Update Dockerfile

Modify `agent/Dockerfile` if you need additional system dependencies:

```dockerfile
FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    chromium-browser \
    # Add your system dependencies here
    && rm -rf /var/lib/apt/lists/*
```

### 4. Configure Environment

Update `docker-compose.yml` with your environment variables:

```yaml
environment:
  - AGENT_NAME=My Custom Agent
  - AGENT_VERSION=1.0.0
  - GITHUB_URL=https://github.com/your-username/your-repo
  - HAS_RL=true  # If using reinforcement learning
  - LOG_LEVEL=DEBUG
```

## Testing

### Local Testing

```bash
# Start the agent
docker-compose up -d

# Run tests
docker-compose exec agent python -m pytest tests/

# Check logs
docker-compose logs -f agent
```

### Integration Testing

The deployment controller will automatically test your agent by:

1. **Building** your Docker image
2. **Starting** the container
3. **Health checking** the `/health` endpoint
4. **Sending test tasks** to `/api/task`
5. **Validating** response format

## Action Types

Your agent should return actions in this format:

```python
# Navigation
{
    "type": "navigate",
    "url": "https://example.com"
}

# Click
{
    "type": "click",
    "selector": "button.login",
    "coordinates": [100, 200]  # Optional
}

# Type text
{
    "type": "type",
    "selector": "input[name='email']",
    "text": "user@example.com"
}

# Scroll
{
    "type": "scroll",
    "direction": "down",  # or "up"
    "amount": 500
}

# Wait
{
    "type": "wait",
    "duration": 2.0  # seconds
}

# Screenshot
{
    "type": "screenshot"
}

# Extract text
{
    "type": "extract",
    "selector": "h1.title",
    "attribute": "textContent"  # or "innerHTML", "href", etc.
}
```

## Best Practices

1. **Error Handling**: Always handle exceptions gracefully
2. **Logging**: Use structured logging for debugging
3. **Performance**: Keep execution time reasonable (< 30 seconds)
4. **Reliability**: Make actions robust and handle edge cases
5. **Security**: Don't expose sensitive information in logs
6. **Testing**: Write comprehensive tests for your agent logic

## Deployment

Once your agent is ready:

1. **Push to GitHub**: Make sure your repository follows the standard
2. **Test Locally**: Verify everything works with `docker-compose up`
3. **Submit to Validator**: The deployment controller will automatically deploy and test your agent

## Support

- Check the [Miner Repository Standard](../MINER_REPOSITORY_STANDARD.md) for detailed requirements
- Review the [Deployment Controller documentation](../README.md) for integration details
- Open an issue in the Autoppia repository for questions

## License

This template is provided under the same license as the Autoppia project.
