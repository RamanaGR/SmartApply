#!/usr/bin/env python3
"""
SmartApply Run Wrapper
Convenience script to run SmartApply without explicitly typing src/main.py
"""

import sys
import subprocess
from pathlib import Path

def main():
    """Run SmartApply main module."""
    src_dir = Path(__file__).parent / "src"
    
    # Run main.py with all arguments passed through
    result = subprocess.run(
        [sys.executable, str(src_dir / "main.py")] + sys.argv[1:],
        cwd=Path(__file__).parent
    )
    
    sys.exit(result.returncode)

if __name__ == "__main__":
    main()
