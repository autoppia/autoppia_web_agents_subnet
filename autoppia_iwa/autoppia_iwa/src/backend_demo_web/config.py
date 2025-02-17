import sys
from pathlib import Path

from autoppia_iwa.src.data_generation.domain.classes import WebProject

sys.path.append(str(Path(__file__).resolve().parents[3]))

from autoppia_iwa.config.config import DEMO_WEBS_ENDPOINT, DEMO_WEBS_STARTING_PORT
from modules.webs_demo.web_1_demo_django_jobs.events.events import EVENTS_ALLOWED as events_allowed_web_1


def get_frontend_url(index):
    return f"{DEMO_WEBS_ENDPOINT}:{str(8000 + index)}"


def get_backend_url(index: int, symetric=True):
    if symetric:
        return f"{DEMO_WEBS_ENDPOINT}:{str(DEMO_WEBS_STARTING_PORT + (index))}"
    else:
        return f"{DEMO_WEBS_ENDPOINT}:{str(DEMO_WEBS_STARTING_PORT + (index + 1))}"


demo_web_projects = [
    WebProject(
        name="jobs",
        frontend_url=get_frontend_url(index=0),
        backend_url=get_backend_url(index=0),
        events_to_check=events_allowed_web_1,
    )
    # ),
    # DemoWebProject(
    #     name="angular",
    #     frontend_url=get_frontend_url(index=1),
    #     backend_url=get_backend_url(index=1, symetric=False),
    #     events_to_check=events_allowed_web_2,
    # ),
]


def get_demo_webs_projects():
    return demo_web_projects
