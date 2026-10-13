import sys
from pathlib import Path

# Ensure src directory is available on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from bank_statement.cli import main
 
__all__ = ["main"]

if __name__ == "__main__":
    sys.exit(main())
