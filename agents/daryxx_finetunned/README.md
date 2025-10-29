Daryxx Finetuned Agent (Apified)

Overview
- A minimal HTTP agent that wraps an OpenAI fine‑tuned model and returns IWA‑compatible actions for the `/solve_task` endpoint.
- Designed to plug into the miner via `ApifiedWebAgent` (set `USE_APIFIED_AGENT=true` in env).

Run
- Requirements: `pip install fastapi uvicorn openai python-dotenv`
- Env in `.env` (same folder or inherited):
  - `OPENAI_API_KEY=...`
  - `OPENAI_MODEL=ft:gpt-4.1-mini:your-org:autoppia-web-actions:job_id` (replace once available)
  - Optional tuning:
    - `OPENAI_TEMPERATURE=0.0`
    - `OPENAI_MAX_TOKENS=1024`
    - `SYSTEM_PROMPT=You are a web automation planner... (optional)`
    - `AGENT_HOST=0.0.0.0`
    - `AGENT_PORT=8080`

Start server
- From repo root:
  - `python -m uvicorn autoppia_web_agents_subnet.agents.daryxx_finetunned.app:app --host 0.0.0.0 --port 8080`
  - Or: `python autoppia_web_agents_subnet/agents/daryxx_finetunned/app.py`

Hook into miner
- In `.env` used by the miner process (autoppia_iwa_module):
  - `USE_APIFIED_AGENT=true`
  - `AGENT_HOST=<host where this server runs>`
  - `AGENT_PORT=8080`

Contract
- POST `/solve_task` with JSON payload containing at least `{ "id": str, "url": str, "prompt": str }`.
- Responds `{ "task_id": str, "web_agent_id": str, "actions": [ ... ] }`.
- Actions are compatible with `BaseAction.create_action()`. Example:
  - `{ "type": "navigate", "url": "https://example.com" }`
  - `{ "type": "click", "selector": {"type":"attributeValueSelector", "attribute":"custom", "value":"#submit"} }`
  - `{ "type": "type", "selector": { ... }, "value": "hello" }`
