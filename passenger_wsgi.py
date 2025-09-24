import sys
import os

# Add the project directory to the Python path
sys.path.insert(0, os.path.dirname(__file__))

# Import your FastAPI app instance
from main import app as application