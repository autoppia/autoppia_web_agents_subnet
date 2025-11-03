import sys
import types


def _ensure_module(name: str) -> types.ModuleType:
    module = sys.modules.get(name)
    if module is None:
        module = types.ModuleType(name)
        module.__path__ = []  # type: ignore[attr-defined]
        sys.modules[name] = module
    return module


def pytest_configure(config):
    _ensure_module("autoppia_iwa")
    _ensure_module("autoppia_iwa.src")

    demo_pkg = _ensure_module("autoppia_iwa.src.demo_webs")
    if not hasattr(demo_pkg, "__path__"):
        demo_pkg.__path__ = []  # type: ignore[attr-defined]

    demo_classes = types.ModuleType("autoppia_iwa.src.demo_webs.classes")

    class WebProjectStub:
        def __init__(self, name: str = "demo", frontend_url: str = "https://demo"):
            self.name = name
            self.frontend_url = frontend_url

    demo_classes.WebProject = WebProjectStub  # type: ignore[attr-defined]
    sys.modules["autoppia_iwa.src.demo_webs.classes"] = demo_classes

    config.addinivalue_line("markers", "requires_finney: integration test hitting a live Subtensor network")

    domain_pkg = _ensure_module("autoppia_iwa.src.data_generation")
    if not hasattr(domain_pkg, "__path__"):
        domain_pkg.__path__ = []  # type: ignore[attr-defined]
    domain_classes = types.ModuleType("autoppia_iwa.src.data_generation.domain.classes")

    class TaskStub:
        _id_counter = 0

        def __init__(self, url: str = "https://example.com", prompt: str = "prompt", tests=None):
            self.url = url
            self.prompt = prompt
            self.tests = tests or []
            TaskStub._id_counter += 1
            self.id = f"task-{TaskStub._id_counter}"
            self._seed_value = None

        def nested_model_dump(self):
            return {"url": self.url, "prompt": self.prompt, "tests": self.tests, "id": self.id}

        def assign_seed_to_url(self):
            if self._seed_value is None:
                self._seed_value = 0

    domain_classes.Task = TaskStub  # type: ignore[attr-defined]

    class TaskGenerationConfig:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    domain_classes.TaskGenerationConfig = TaskGenerationConfig  # type: ignore[attr-defined]
    domain_classes.TestUnion = object  # type: ignore[attr-defined]
    sys.modules["autoppia_iwa.src.data_generation.domain.classes"] = domain_classes

    web_agents_pkg = types.ModuleType("autoppia_iwa.src.web_agents.classes")

    class TaskSolutionStub:
        def __init__(self, task_id: str, actions=None, web_agent_id: str = "0"):
            self.task_id = task_id
            self.actions = actions or []
            self.web_agent_id = web_agent_id

    web_agents_pkg.TaskSolution = TaskSolutionStub  # type: ignore[attr-defined]
    sys.modules["autoppia_iwa.src.web_agents.classes"] = web_agents_pkg


    exec_pkg = _ensure_module("autoppia_iwa.src.execution")
    if not hasattr(exec_pkg, "__path__"):
        exec_pkg.__path__ = []  # type: ignore[attr-defined]

    actions_pkg = _ensure_module("autoppia_iwa.src.execution.actions")
    if not hasattr(actions_pkg, "__path__"):
        actions_pkg.__path__ = []  # type: ignore[attr-defined]

    actions_module = types.ModuleType("autoppia_iwa.src.execution.actions.actions")
    actions_module.AllActionsUnion = object  # type: ignore[attr-defined]
    sys.modules["autoppia_iwa.src.execution.actions.actions"] = actions_module

    base_module = types.ModuleType("autoppia_iwa.src.execution.actions.base")

    class _BaseActionStub:
        @staticmethod
        def create_action(data):
            return types.SimpleNamespace(**data)

    base_module.BaseAction = _BaseActionStub  # type: ignore[attr-defined]
    sys.modules["autoppia_iwa.src.execution.actions.base"] = base_module
    

    eval_pkg = _ensure_module("autoppia_iwa.src.evaluation")
    if not hasattr(eval_pkg, "__path__"):
        eval_pkg.__path__ = []  # type: ignore[attr-defined]

    evaluator_pkg = _ensure_module("autoppia_iwa.src.evaluation.evaluator")
    if not hasattr(evaluator_pkg, "__path__"):
        evaluator_pkg.__path__ = []  # type: ignore[attr-defined]

    evaluator_module = types.ModuleType("autoppia_iwa.src.evaluation.evaluator.evaluator")

    class _EvaluatorConfigStub:
        def __init__(self, **_):
            pass

    class _ConcurrentEvaluatorStub:
        def __init__(self, *_):
            pass

        async def evaluate_task_solutions(self, *, task, task_solutions):
            n = len(task_solutions)
            scores = [1.0 for _ in range(n)]
            test_results = [[{"success": True}] for _ in range(n)]
            evaluation_results = [{"final_score": 1.0} for _ in range(n)]
            return scores, test_results, evaluation_results

    evaluator_module.ConcurrentEvaluator = _ConcurrentEvaluatorStub  # type: ignore[attr-defined]
    evaluator_module.EvaluatorConfig = _EvaluatorConfigStub  # type: ignore[attr-defined]
    sys.modules["autoppia_iwa.src.evaluation.evaluator.evaluator"] = evaluator_module
    

    demo_config = types.ModuleType("autoppia_iwa.src.demo_webs.config")
    demo_config.demo_web_projects = [demo_classes.WebProject()]  # type: ignore[attr-defined]
    sys.modules["autoppia_iwa.src.demo_webs.config"] = demo_config
    


    app_pkg = _ensure_module("autoppia_iwa.src.data_generation.application")
    if not hasattr(app_pkg, "__path__"):
        app_pkg.__path__ = []  # type: ignore[attr-defined]

    pipeline_module = types.ModuleType("autoppia_iwa.src.data_generation.application.tasks_generation_pipeline")

    class TaskGenerationPipeline:
        def __init__(self, *_, **__):
            pass

        async def generate(self):
            return []

    pipeline_module.TaskGenerationPipeline = TaskGenerationPipeline  # type: ignore[attr-defined]
    sys.modules["autoppia_iwa.src.data_generation.application.tasks_generation_pipeline"] = pipeline_module
    bootstrap_module = types.ModuleType("autoppia_iwa.src.bootstrap")

    class _AppBootstrapStub:
        def __init__(self, **_):
            pass

    bootstrap_module.AppBootstrap = _AppBootstrapStub  # type: ignore[attr-defined]
    sys.modules["autoppia_iwa.src.bootstrap"] = bootstrap_module




import pytest


@pytest.fixture(autouse=True)
def reset_mock_network_fixture():
    from autoppia_web_agents_subnet.base.mock import reset_mock_network

    reset_mock_network()
    yield
    reset_mock_network()

