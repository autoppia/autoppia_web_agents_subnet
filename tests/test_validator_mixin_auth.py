import base64
import sys
from pathlib import Path
from types import SimpleNamespace
import types

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
iwa_module_root = PROJECT_ROOT / "autoppia_iwa_module"
if str(iwa_module_root) not in sys.path:
    sys.path.insert(0, str(iwa_module_root))

def _ensure_package(name: str) -> types.ModuleType:
    module = sys.modules.get(name)
    if module is None:
        module = types.ModuleType(name)
        module.__path__ = []  # type: ignore[attr-defined]
        sys.modules[name] = module
    return module


_ensure_package("autoppia_iwa")
_ensure_package("autoppia_iwa.src")
_ensure_package("autoppia_iwa.src.demo_webs")
demo_classes = types.ModuleType("autoppia_iwa.src.demo_webs.classes")

class WebProjectStub:  # pragma: no cover - simple stub
    ...


demo_classes.WebProject = WebProjectStub  # type: ignore[attr-defined]
sys.modules["autoppia_iwa.src.demo_webs.classes"] = demo_classes

_ensure_package("autoppia_iwa.src.data_generation")
_ensure_package("autoppia_iwa.src.data_generation.domain")
domain_classes = types.ModuleType("autoppia_iwa.src.data_generation.domain.classes")

class TaskStub:  # pragma: no cover - simple stub
    ...


domain_classes.Task = TaskStub  # type: ignore[attr-defined]
sys.modules["autoppia_iwa.src.data_generation.domain.classes"] = domain_classes

_ensure_package("autoppia_iwa.src.web_agents")
web_agents_classes = types.ModuleType("autoppia_iwa.src.web_agents.classes")

class TaskSolutionStub:  # pragma: no cover - simple stub
    ...


web_agents_classes.TaskSolution = TaskSolutionStub  # type: ignore[attr-defined]
sys.modules["autoppia_iwa.src.web_agents.classes"] = web_agents_classes

bs4_stub = types.ModuleType("bs4")
bs4_stub.BeautifulSoup = object
sys.modules.setdefault("bs4", bs4_stub)

from autoppia_web_agents_subnet.platform.iwa import main as iwa_main  # noqa:E402
from autoppia_web_agents_subnet.platform.iwa.validator_mixin import (  # noqa:E402
    ValidatorPlatformMixin,
)


class _HotkeyMock:
    def __init__(self) -> None:
        self.ss58_address = "5MockHotkeyAddress"
        self.calls: list[bytes] = []

    def sign(self, payload: bytes) -> bytes:
        self.calls.append(payload)
        return b"mock-signature"


def _mixin_with_wallet(message: str = "test message") -> tuple[ValidatorPlatformMixin, _HotkeyMock]:
    mixin = object.__new__(ValidatorPlatformMixin)
    hotkey = _HotkeyMock()
    mixin.wallet = SimpleNamespace(
        hotkey=hotkey,
        coldkeypub=SimpleNamespace(ss58_address="5MockCold"),
    )
    mixin.uid = 1
    mixin.version = "test"
    mixin._validator_auth_message = message
    mixin._auth_warning_emitted = False
    mixin._log_iwap_phase = lambda *args, **kwargs: None
    return mixin, hotkey


def test_sign_and_verify() -> None:
    message = "I am a honest validator"
    mixin, hotkey = _mixin_with_wallet(message)

    headers = mixin._build_iwap_auth_headers()

    expected_signature = base64.b64encode(b"mock-signature").decode("ascii")
    assert headers == {
        iwa_main.VALIDATOR_HOTKEY_HEADER: hotkey.ss58_address,
        iwa_main.VALIDATOR_SIGNATURE_HEADER: expected_signature,
    }
    assert hotkey.calls == [message.encode("utf-8")]
