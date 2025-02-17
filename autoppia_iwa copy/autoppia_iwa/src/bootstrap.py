from .di_container import DIContainer


class AppBootstrap:
    def __init__(self):
        self.configure_dependency_injection()

    def configure_dependency_injection(self):
        self.container = DIContainer()
