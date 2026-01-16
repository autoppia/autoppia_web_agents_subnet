import sys
import types
import os
from pathlib import Path

# Set TESTING environment variable before any imports
os.environ["TESTING"] = "True"

# Ensure repo root is on sys.path so autoppia_web_agents_subnet imports work in tests
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


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
    domain_classes = types.ModuleType("autoppia_iwa.src.data_generation.tasks.classes")

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
    sys.modules["autoppia_iwa.src.data_generation.tasks.classes"] = domain_classes

    web_agents_pkg = types.ModuleType("autoppia_iwa.src.web_agents.classes")

    class TaskSolutionStub:
        def __init__(self, task_id: str, actions=None, web_agent_id: str = "0"):
            self.task_id = task_id
            self.actions = actions or []
            self.web_agent_id = web_agent_id

    web_agents_pkg.TaskSolution = TaskSolutionStub  # type: ignore[attr-defined]
    sys.modules["autoppia_iwa.src.web_agents.classes"] = web_agents_pkg

    # Minimal stub for CUA interfaces (only needed for imports; tests patch
    # concrete implementations with fakes).
    cua_module = types.ModuleType("autoppia_iwa.src.web_agents.cua")

    class _ApifiedWebCUAStub:
        def __init__(self, base_url: str, **_: object):
            self.base_url = base_url

        async def act(self, *_, **__):
            return []

    cua_module.ApifiedWebCUA = _ApifiedWebCUAStub  # type: ignore[attr-defined]
    sys.modules["autoppia_iwa.src.web_agents.cua"] = cua_module


    exec_pkg = _ensure_module("autoppia_iwa.src.execution")
    if not hasattr(exec_pkg, "__path__"):
        exec_pkg.__path__ = []  # type: ignore[attr-defined]

    actions_pkg = _ensure_module("autoppia_iwa.src.execution.actions")
    if not hasattr(actions_pkg, "__path__"):
        actions_pkg.__path__ = []  # type: ignore[attr-defined]

    actions_module = types.ModuleType("autoppia_iwa.src.execution.actions.actions")

    class _ClickActionStub:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)

    actions_module.ClickAction = _ClickActionStub  # type: ignore[attr-defined]
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

    # Lightweight stub for the stateful evaluator used by evaluation.eval.
    stateful_module = types.ModuleType("autoppia_iwa.src.evaluation.stateful_evaluator")

    class ScoreDetailsStub:
        def __init__(self, raw_score: float = 0.0, tests_passed: int = 0, total_tests: int = 0, success: bool = False):
            self.raw_score = float(raw_score)
            self.tests_passed = int(tests_passed)
            self.total_tests = int(total_tests)
            self.success = bool(success)

    class AsyncStatefulEvaluatorStub:
        def __init__(self, *_, **__):
            self._step_called = False

        async def reset(self):
            # First reset returns zero score.
            return types.SimpleNamespace(
                score=ScoreDetailsStub(raw_score=0.0, tests_passed=0, total_tests=1, success=False),
                snapshot=types.SimpleNamespace(html="", url="https://example.com"),
            )

        async def step(self, action):  # noqa: ARG002
            # Any step moves score to 1.0 and marks success.
            self._step_called = True
            return types.SimpleNamespace(
                score=ScoreDetailsStub(raw_score=1.0, tests_passed=1, total_tests=1, success=True),
                snapshot=types.SimpleNamespace(html="", url="https://example.com/after"),
            )

        async def close(self):
            return None

    stateful_module.AsyncStatefulEvaluator = AsyncStatefulEvaluatorStub  # type: ignore[attr-defined]
    stateful_module.ScoreDetails = ScoreDetailsStub  # type: ignore[attr-defined]
    sys.modules["autoppia_iwa.src.evaluation.stateful_evaluator"] = stateful_module

    demo_config = types.ModuleType("autoppia_iwa.src.demo_webs.config")
    demo_config.demo_web_projects = [demo_classes.WebProject()]  # type: ignore[attr-defined]
    sys.modules["autoppia_iwa.src.demo_webs.config"] = demo_config
    


    app_pkg = _ensure_module("autoppia_iwa.src.data_generation.application")
    if not hasattr(app_pkg, "__path__"):
        app_pkg.__path__ = []  # type: ignore[attr-defined]

    pipeline_module = types.ModuleType("autoppia_iwa.src.data_generation.tasks.pipeline")

    class TaskGenerationPipeline:
        def __init__(self, *_, **__):
            pass

        async def generate(self):
            return []

    pipeline_module.TaskGenerationPipeline = TaskGenerationPipeline  # type: ignore[attr-defined]
    sys.modules["autoppia_iwa.src.data_generation.tasks.pipeline"] = pipeline_module
    bootstrap_module = types.ModuleType("autoppia_iwa.src.bootstrap")

    class _AppBootstrapStub:
        def __init__(self, **_):
            pass

    bootstrap_module.AppBootstrap = _AppBootstrapStub  # type: ignore[attr-defined]
    sys.modules["autoppia_iwa.src.bootstrap"] = bootstrap_module




import pytest


# Validator fixtures - imported after pytest_configure sets up stubs
@pytest.fixture
def mock_validator_config():
    """Minimal validator configuration for testing."""
    return {
        "round_size_epochs": 2.0,
        "minimum_start_block": 1000,
        "settlement_fraction": 0.8,
        "season_size_epochs": 10.0,
        "netuid": 99,
        "subtensor": {
            "network": "test",
            "chain_endpoint": "ws://127.0.0.1:9944",
        },
        "wallet": {
            "name": "test_validator",
            "hotkey": "test_hotkey",
        },
    }


@pytest.fixture
def round_manager(mock_validator_config):
    """Create a RoundManager instance with test configuration."""
    from autoppia_web_agents_subnet.validator.round_manager import RoundManager
    
    return RoundManager(
        round_size_epochs=mock_validator_config["round_size_epochs"],
        minimum_start_block=mock_validator_config["minimum_start_block"],
        settlement_fraction=mock_validator_config["settlement_fraction"],
    )


@pytest.fixture
def season_manager(mock_validator_config):
    """Create a SeasonManager instance with test configuration."""
    from unittest.mock import AsyncMock, Mock
    from autoppia_web_agents_subnet.validator.season_manager import SeasonManager
    
    manager = SeasonManager()
    # Override with test config values
    manager.minimum_start_block = mock_validator_config["minimum_start_block"]
    manager.season_size_epochs = mock_validator_config["season_size_epochs"]
    manager.season_block_length = int(manager.BLOCKS_PER_EPOCH * manager.season_size_epochs)
    
    # Mock generate_season_tasks to avoid hanging on complex imports
    # Return a list with one mock task
    mock_task = Mock()
    mock_task.id = "test-task-1"
    manager.generate_season_tasks = AsyncMock(return_value=[mock_task])
    return manager


@pytest.fixture
def dummy_validator(mock_validator_config):
    """Create a mock validator with all necessary attributes and mixins."""
    from unittest.mock import Mock, AsyncMock
    from autoppia_web_agents_subnet.validator.round_manager import RoundManager
    from types import SimpleNamespace
    
    validator = Mock()
    
    # Convert config dict to object with attributes
    validator.config = SimpleNamespace(**mock_validator_config)
    validator.block = 1000
    validator.uid = 0
    validator.version = "1.0.0"
    
    # Wallet mock
    validator.wallet = Mock()
    validator.wallet.hotkey = Mock()
    validator.wallet.hotkey.ss58_address = "test_hotkey_address"
    
    # Subtensor mock
    validator.subtensor = Mock()
    # Make get_current_block return increasing values to avoid infinite loops in wait functions
    validator._mock_block_counter = 1000
    def get_increasing_block():
        validator._mock_block_counter += 1
        return validator._mock_block_counter
    validator.subtensor.get_current_block = Mock(side_effect=get_increasing_block)
    
    # Dendrite mock
    validator.dendrite = Mock()
    validator.dendrite.query = AsyncMock(return_value=[])  # Return empty list by default
    
    # Managers
    validator.round_manager = RoundManager(
        round_size_epochs=mock_validator_config["round_size_epochs"],
        minimum_start_block=mock_validator_config["minimum_start_block"],
        settlement_fraction=mock_validator_config["settlement_fraction"],
    )
    # Mock get_wait_info to return plenty of time for evaluation
    validator.round_manager.get_wait_info = Mock(return_value={
        "minutes_to_settlement": 60.0,  # Plenty of time
        "blocks_to_settlement": 300,
        "minutes_to_target": 120.0,  # Plenty of time
        "blocks_to_target": 600,
    })
    
    validator.season_manager = Mock()
    validator.season_manager.generate_season_tasks = AsyncMock(return_value=[])
    validator.season_manager.get_season_tasks = AsyncMock(return_value=[])
    # Mock should_start_new_season to return False by default (tests can override)
    validator.season_manager.should_start_new_season = Mock(return_value=False)
    # Add task_generated_season attribute for tests
    validator.season_manager.task_generated_season = 0
    
    # Agent tracking
    validator.agents_dict = {}
    validator.agents_queue = Mock()
    validator.agents_queue.empty = Mock(return_value=True)
    validator.agents_queue.get = Mock(side_effect=Exception("Queue empty"))
    validator.agents_queue.put = Mock()
    
    # Sandbox manager (mocked)
    validator.sandbox_manager = Mock()
    
    # Metagraph mock
    validator.metagraph = Mock()
    validator.metagraph.n = 10
    validator.metagraph.uids = list(range(10))
    validator.metagraph.S = [15000.0] * 10  # Stake values (old format) - above MIN_VALIDATOR_STAKE_FOR_CONSENSUS_TAO
    validator.metagraph.stake = [15000.0] * 10  # Stake values (new format)
    validator.metagraph.hotkeys = [f"hotkey{i}" for i in range(10)]
    validator.metagraph.coldkeys = [f"coldkey{i}" for i in range(10)]
    validator.metagraph.axons = [Mock(ip="127.0.0.1", port=8000 + i) for i in range(10)]
    
    # Async methods
    validator.sync = AsyncMock()
    validator.set_weights = AsyncMock()
    validator.update_scores = AsyncMock()
    validator._get_async_subtensor = AsyncMock()
    validator._log_round_completion = Mock()
    
    # Mixin methods (mocked instead of inherited)
    validator._start_round = AsyncMock()
    validator._perform_handshake = AsyncMock()
    validator._wait_for_minimum_start_block = AsyncMock(return_value=False)
    validator._wait_until_specific_block = AsyncMock()
    validator._run_evaluation_phase = AsyncMock(return_value=0)
    validator._run_settlement_phase = AsyncMock()
    
    # Round ID for logging
    validator.current_round_id = "test-round-1"
    validator._current_round_number = 1
    validator._last_round_winner_uid = None
    validator._finalized_this_round = False
    
    return validator


@pytest.fixture
def validator_with_agents(dummy_validator):
    """Create a validator with pre-populated agent information."""
    from unittest.mock import Mock
    from autoppia_web_agents_subnet.validator.models import AgentInfo
    import queue
    
    # Replace mock queue with real queue
    dummy_validator.agents_queue = queue.Queue()
    
    # Add 3 test agents
    for uid in [1, 2, 3]:
        agent = AgentInfo(
            uid=uid,
            agent_name=f"test_agent_{uid}",
            github_url=f"https://github.com/test/agent{uid}",
            score=0.0,
        )
        dummy_validator.agents_dict[uid] = agent
        dummy_validator.agents_queue.put(agent)
    
    return dummy_validator


def _bind_evaluation_mixin(validator):
    """Helper to bind evaluation mixin methods to validator (lazy import to avoid circular deps)."""
    from autoppia_web_agents_subnet.validator.evaluation.mixin import ValidatorEvaluationMixin
    validator._run_evaluation_phase = ValidatorEvaluationMixin._run_evaluation_phase.__get__(validator, type(validator))
    return validator


def _bind_settlement_mixin(validator):
    """Helper to bind settlement mixin methods to validator (lazy import to avoid circular deps)."""
    from autoppia_web_agents_subnet.validator.settlement.mixin import ValidatorSettlementMixin
    validator._run_settlement_phase = ValidatorSettlementMixin._run_settlement_phase.__get__(validator, type(validator))
    validator._calculate_final_weights = ValidatorSettlementMixin._calculate_final_weights.__get__(validator, type(validator))
    validator._burn_all = ValidatorSettlementMixin._burn_all.__get__(validator, type(validator))
    # Don't bind _wait_until_specific_block - keep it as AsyncMock to avoid infinite loops in tests
    # validator._wait_until_specific_block = ValidatorSettlementMixin._wait_until_specific_block.__get__(validator, type(validator))
    return validator


def _bind_settlement_mixin_with_wait(validator):
    """Helper to bind settlement mixin methods including _wait_until_specific_block."""
    from autoppia_web_agents_subnet.validator.settlement.mixin import ValidatorSettlementMixin
    validator._run_settlement_phase = ValidatorSettlementMixin._run_settlement_phase.__get__(validator, type(validator))
    validator._calculate_final_weights = ValidatorSettlementMixin._calculate_final_weights.__get__(validator, type(validator))
    validator._burn_all = ValidatorSettlementMixin._burn_all.__get__(validator, type(validator))
    validator._wait_until_specific_block = ValidatorSettlementMixin._wait_until_specific_block.__get__(validator, type(validator))
    return validator


def _bind_round_start_mixin(validator):
    """Helper to bind round start mixin methods to validator (lazy import to avoid circular deps)."""
    from autoppia_web_agents_subnet.validator.round_start.mixin import ValidatorRoundStartMixin
    validator._start_round = ValidatorRoundStartMixin._start_round.__get__(validator, type(validator))
    validator._perform_handshake = ValidatorRoundStartMixin._perform_handshake.__get__(validator, type(validator))
    validator._wait_for_minimum_start_block = ValidatorRoundStartMixin._wait_for_minimum_start_block.__get__(validator, type(validator))
    return validator


@pytest.fixture
def season_tasks():
    """Create mock season tasks for testing."""
    from autoppia_web_agents_subnet.validator.models import TaskWithProject
    from unittest.mock import Mock
    
    # Create 5 mock tasks (to match test expectations)
    tasks = []
    for i in range(5):
        task = Mock()
        task.id = f"task-{i}"
        task.url = f"https://example.com/task{i}"
        task.prompt = f"Test task {i}"
        task.tests = []
        
        task_with_project = TaskWithProject(
            project=None,
            task=task
        )
        tasks.append(task_with_project)
    
    return tasks


@pytest.fixture
def mock_metagraph():
    """Create a mock metagraph for testing."""
    from unittest.mock import Mock
    
    metagraph = Mock()
    metagraph.n = 10
    metagraph.uids = list(range(10))
    metagraph.S = [15000.0] * 10
    metagraph.stake = [15000.0] * 10
    metagraph.hotkeys = [f"hotkey{i}" for i in range(10)]
    metagraph.axons = [Mock(ip="127.0.0.1", port=8000 + i) for i in range(10)]
    
    return metagraph


@pytest.fixture
def mock_ipfs_client():
    """Create a mock IPFS client for testing."""
    from unittest.mock import Mock, AsyncMock
    
    # Storage for uploaded data
    storage = {}
    cid_counter = [0]
    
    async def mock_add_json(data, **kwargs):
        cid_counter[0] += 1
        cid = f"QmTestCID{cid_counter[0]}"
        storage[cid] = data
        return (cid, f"sha256hex{cid_counter[0]}", len(str(data)))
    
    async def mock_get_json(cid, **kwargs):
        data = storage.get(cid, {"scores": {}})
        return (data, None, None)
    
    client = Mock()
    client.add_json_async = AsyncMock(side_effect=mock_add_json)
    client.get_json_async = AsyncMock(side_effect=mock_get_json)
    
    return client


@pytest.fixture
def mock_async_subtensor():
    """Create a mock async subtensor for testing."""
    from unittest.mock import Mock, AsyncMock
    
    subtensor = Mock()
    subtensor.commitments = {}
    subtensor.stakes = {}
    subtensor.get_current_block = Mock(return_value=1000)
    subtensor.commit = AsyncMock(return_value=True)
    subtensor.set_weights = AsyncMock(return_value=True)
    
    return subtensor
