import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

# Allow `from stacks.bitcoin_monitor_stack import ...` in CDK tests
_AWS_DIR = str(Path(__file__).parent.parent / "aws")
if _AWS_DIR not in sys.path:
    sys.path.insert(0, _AWS_DIR)

# Must happen before any lambda module is imported — their module-level
# boto3.client / boto3.resource calls would otherwise hit AWS.
os.environ.setdefault("IP_PROVIDER_HOSTNAME", "test.duckdns.org")
os.environ.setdefault("BITCOIN_PORT", "8333")
os.environ.setdefault("NODE_ID", "lasvegas")
os.environ.setdefault("HEARTBEAT_SECRET", "test-secret")

sys.modules["boto3"] = MagicMock()
