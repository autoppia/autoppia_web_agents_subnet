__version__ = "10.1.0"
__least_acceptable_version__ = "2.1.1"
version_split = __version__.split(".")
version_url = "https://raw.githubusercontent.com/autoppia/autoppia_web_agents_subnet/main/autoppia_web_agents_subnet/__init__.py"

__spec_version__ = (1000 * int(version_split[0])) + (10 * int(version_split[1])) + (1 * int(version_split[2]))
