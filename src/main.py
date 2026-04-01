"""
SmartApply - Main Entry Point
Email automation tool for job applications using local LLM and Gmail.

Usage:
    python run.py              # Send emails configured in config.yaml
    python run.py --dry-run    # Preview emails without sending
"""

import argparse
import sys
from pathlib import Path

# Force UTF-8 encoding for standard output across all platforms to avoid emoji crashes
try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.orchestrator import SmartApplyOrchestrator


def parse_arguments() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="SmartApply - Automated email generation and sending for job applications",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Usage:
  python run.py              # Send emails configured in config.yaml
  python run.py --dry-run    # Preview emails without sending
        """
    )

    parser.add_argument(
        "--config",
        default="config.yaml",
        help="Path to config file (default: config.yaml)"
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview without sending emails"
    )

    parser.add_argument(
        "--user",
        help="Run for a specific user (looks in resume/<USER>/ for credentials and resume files)"
    )

    return parser.parse_args()


def main():
    """Main entry point."""
    args = parse_arguments()

    # Check for .env file
    env_path = Path(".env")
    if not env_path.exists():
        print("Warning: .env file not found. Using environment variables or prompting at runtime.")
    else:
        from dotenv import load_dotenv
        load_dotenv()

    try:
        orchestrator = SmartApplyOrchestrator(config_file=args.config)
        exit_code = orchestrator.run(args)
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\nInterrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"Fatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
