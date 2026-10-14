"""PyInstaller entry point (kept outside the package so imports are absolute)."""
import sys

from codeagent.cli import main

if __name__ == "__main__":
    sys.exit(main())
