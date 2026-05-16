#!/usr/bin/env python3
"""
Main entry point for autonomous feature generation.
Run with: python run_autonomous.py
"""
import sys
import os
from pathlib import Path

# Add project to path
AGENTS_DIR = Path(__file__).parent
sys.path.insert(0, str(AGENTS_DIR.parent.parent / "src"))

# Set working directory
os.chdir(AGENTS_DIR.parent.parent)

if __name__ == "__main__":
    from autonomous.run_orchestrator import main
    main()