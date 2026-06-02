# Harvester Runtime

Validators evaluate miner harvesters by cloning the committed repository,
starting it inside the sandbox image, calling `POST /find_trayectory`, and
replaying the returned trajectory with IWA.

Miner repositories should implement:

- `GET /health`
- `POST /find_trayectory`

The `/find_trayectory` response must include `trajectory`, a list of IWA tool
calls shaped as:

```json
{"name": "click", "arguments": {"selector": {"type": "attributeValueSelector", "attribute": "id", "value": "submit"}}}
```

Claude Code harvesters do not need custom Docker images. The validator sandbox
image provides the `claude` CLI, and the validator injects:

- `ANTHROPIC_API_KEY`
- `AUTOPPIA_HARVESTER_CLAUDE_MODEL`
- `AUTOPPIA_HARVESTER_TIMEOUT_SECONDS`

For local multi-validator testing, each validator process must use a unique
gateway name and host port:

```bash
SANDBOX_GATEWAY_INSTANCE=validator492
SANDBOX_GATEWAY_PORT_OFFSET=12
SANDBOX_INSTANCE=validator492
```

The sandbox gateway readiness check validates both `/health` and an admin
endpoint with the generated admin token. If another gateway already owns the
host port, startup fails before evaluation instead of producing later `403`
cost-accounting errors.
