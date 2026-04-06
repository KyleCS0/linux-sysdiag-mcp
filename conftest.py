import sys
import os

# Add project root to sys.path so tests can import top-level modules
# regardless of which directory pytest is invoked from.
sys.path.insert(0, os.path.dirname(__file__))
