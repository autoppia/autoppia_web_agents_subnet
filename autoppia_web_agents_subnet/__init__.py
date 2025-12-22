__version__ = "11.1.0"
__least_acceptable_version__ = "11.0.0"
version_split = __version__.split(".")
version_url = "https://raw.githubusercontent.com/autoppia/autoppia_web_agents_subnet/main/autoppia_web_agents_subnet/__init__.py"

__spec_version__ = (1000 * int(version_split[0])) + (10 * int(version_split[1])) + (1 * int(version_split[2]))
