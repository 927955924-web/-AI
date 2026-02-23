import sys
import os

if __package__ is None:
    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from src.ui.app import main
from src.infrastructure.db import connect, init_db

if __name__ == "__main__":
    conn = connect()
    init_db(conn)
    main(conn)
