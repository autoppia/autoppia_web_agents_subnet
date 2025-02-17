import asyncio
import aiohttp

from autoppia_iwa.src.data_generation.domain.classes import Task
from autoppia_iwa.src.execution.actions.actions import ACTION_CLASS_MAP, BaseAction
from autoppia_iwa.src.web_agents.classes import TaskSolution
from autoppia_iwa.src.web_agents.base import BaseAgent


class ApifiedWebAgent(BaseAgent):
    """
    Calls a remote /solve_task endpoint and rebuilds a TaskSolution.
    """

    def __init__(self, name: str, host: str, port: int, timeout=45):
        self.name = name
        self.base_url = f"http://{host}:{port}"
        self.timeout = timeout
        super().__init__()

    async def solve_task(self, task: Task) -> TaskSolution:
        timeout = aiohttp.ClientTimeout(total=self.timeout)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            try:
                async with session.post(f"{self.base_url}/solve_task", json=task.nested_model_dump()) as response:
                    response_json = await response.json()

                    # Extract data
                    task_data = response_json.get("task", {})
                    actions_data = response_json.get("actions", [])
                    web_agent_id = response_json.get("web_agent_id", "unknown")

                    # Rebuild
                    rebuilt_task = Task.from_dict(task_data)
                    rebuilt_actions = []
                    for action_data in actions_data:
                        action_type = action_data.get("type")
                        if action_type in ACTION_CLASS_MAP:
                            action_class = ACTION_CLASS_MAP[action_type]
                            action = action_class.model_validate(action_data)
                            rebuilt_actions.append(action)
                        else:
                            print(f"Warning: Unknown action type {action_type}")
                            action = BaseAction.model_validate(action_data)
                            rebuilt_actions.append(action)

                    print(f"Rebuilt Task: {rebuilt_task}")
                    print(f"Rebuilt Actions: {rebuilt_actions}")

                    return TaskSolution(task=rebuilt_task, actions=rebuilt_actions, web_agent_id=web_agent_id)
            except Exception as e:
                print(f"Error during HTTP request: {e}")
                return TaskSolution(task=task, actions=[], web_agent_id="unknown")

    def solve_task_sync(self, task: Task) -> TaskSolution:
        return asyncio.run(self.solve_task(task))
