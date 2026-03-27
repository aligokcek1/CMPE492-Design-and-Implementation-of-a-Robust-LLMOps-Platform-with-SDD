import sys
import os

# Add frontend/ to sys.path so `src.*` imports work from any pytest invocation
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
