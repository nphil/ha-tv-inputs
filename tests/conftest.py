"""Keep pytest from importing the integration package.

``__init__.py`` needs a Home Assistant runtime; ``logic.py`` does not. The
tests import ``logic`` directly from the package directory.
"""

collect_ignore = ["../custom_components"]
