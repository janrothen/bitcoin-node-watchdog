import os
import sys
from unittest.mock import MagicMock

# Must happen before any lambda module is imported — their module-level
# boto3.client / boto3.resource calls would otherwise hit AWS.
os.environ.setdefault("IP_PROVIDER_HOSTNAME", "test.duckdns.org")
os.environ.setdefault("BITCOIN_PORT", "8333")
os.environ.setdefault("NODE_ID", "lasvegas")
os.environ.setdefault("HEARTBEAT_SECRET", "test-secret")

sys.modules["boto3"] = MagicMock()
