import os
import sys
from unittest.mock import MagicMock

# Must happen before any lambda module is imported — their module-level
# boto3.client / boto3.resource calls would otherwise hit AWS.
os.environ.setdefault("TABLE_NAME", "test-table")
os.environ.setdefault("DUCKDNS_HOSTNAME", "test.duckdns.org")
os.environ.setdefault("BITCOIN_PORT", "8333")

sys.modules["boto3"] = MagicMock()
