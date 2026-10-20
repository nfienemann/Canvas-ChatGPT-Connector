"""Run checks with privately supplied TEST_DATABASE_URL."""

import os
import sys

import pytest

if not os.environ.get("TEST_DATABASE_URL"):
    raise SystemExit("Set TEST_DATABASE_URL privately to a disposable PostgreSQL database.")
raise SystemExit(pytest.main(sys.argv[1:]))
