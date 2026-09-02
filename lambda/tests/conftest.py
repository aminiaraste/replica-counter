"""Pytest bootstrap for the lambda/ test suite.

Ensures ``handler.py`` (which lives in ``lambda/``, one level up from this
``tests/`` package) is importable regardless of how pytest is invoked
(``pytest`` vs ``python -m pytest``, and regardless of import mode), and
ensures tests never depend on ambient AWS credentials/region from the
developer's environment. moto intercepts these mocked calls, but setting
fake, obviously-fake credentials here is a safety net against a test
accidentally reaching a real AWS account if mocking is ever bypassed.
"""

import os
import sys

_LAMBDA_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _LAMBDA_DIR not in sys.path:
    sys.path.insert(0, _LAMBDA_DIR)

os.environ.setdefault("AWS_DEFAULT_REGION", "eu-central-1")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("AWS_SECURITY_TOKEN", "testing")
os.environ.setdefault("AWS_SESSION_TOKEN", "testing")
