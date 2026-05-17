import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from store.db import init_db
init_db()

from dashboard.app import app
