"""
SmartApply - Main Entry Point
Email automation tool for job applications using local LLM and Gmail.

Usage:
    python main.py my_jobs.csv --model llama3 --limit 5 --dry-run
    python main.py my_jobs.csv --test-mode --delay 1.0
"""

import argparse
import csv
import logging
import sys
import os
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config_loader import load_config
from src.csv_reader import CSVReader
from src.llm_client import OllamaClient, EmailGenerator
from src.email_sender import EmailSenderFactory
from src.validators import PreflightValidator


class SmartApplyOrchestrator:
    """Main orchestrator for the email automation pipeline."""

    def __init__(self, config_file: Optional[str] = None):
        """Initialize orchestrator with configuration."""
        self.config_loader = load_config(config_file)
        self.config = self.config_loader.to_dict()
        self._setup_logging()

    def _setup_logging(self):
        """Setup logging to file and console."""
        log_level = self.config.get("logging", {}).get("level", "INFO")
        log_format = self.config.get("logging", {}).get("format")
        app_log = self.config.get("file_paths", {}).get("app_log", "logs/app.log")

        # Create logs directory if needed
        Path(app_log).parent.mkdir(parents=True, exist_ok=True)

        # Configure root logger
        logging.basicConfig(
            level=log_level,
            format=log_format or "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            handlers=[
                logging.FileHandler(app_log),
                logging.StreamHandler()
            ]
        )

        self.logger = logging.getLogger(__name__)
        self.logger.info("=" * 80)
        self.logger.info("SmartApply - Email Automation Tool")
        self.logger.info(f"Started at {datetime.now()}")
        self.logger.info("=" * 80)

    def run(self, args) -> int:
        """
        Main entry point for the application.
        
        Args:
            args: Parsed command-line arguments
            
        Returns:
            Exit code (0 = success, 1 = failure)
        """
        # Override config with CLI args
        self._apply_cli_overrides(args)

        # Get CSV filename from config first to pass to validation
        csv_filename = self.config.get("input", {}).get("csv_filename")
        if not csv_filename:
            self.logger.error("csv_filename not found in config. Set 'input.csv_filename' in config.yaml")
            return 1

        # Pre-flight validation
        if not self._run_preflight_checks(csv_filename):
            return 1

        # Get column mapping from config (merged with any overrides)
        column_mapping = self.config.get("input", {}).get("column_mapping", {})

        # Load CSV
        csv_reader = CSVReader(
            input_dir=self.config.get("file_paths", {}).get("input_dir", "input"),
            sent_emails_db=self.config.get("file_paths", {}).get("sent_emails_db", "data/sent_emails.json"),
            column_mapping=column_mapping
        )

        try:
            valid_rows, skipped_rows = csv_reader.read_csv(
                csv_filename,
                limit=self.config.get("email_processing", {}).get("email_limit")
            )
        except Exception as e:
            self.logger.error(f"Failed to read CSV: {e}")
            return 1

        # Log skipped rows
        if skipped_rows:
            self.logger.warning(f"Skipped {len(skipped_rows)} invalid rows:")
            for skip_info in skipped_rows[:5]:  # Show first 5
                self.logger.warning(f"  Row {skip_info['row']}: {skip_info['reason']} ({skip_info['email']})")
            if len(skipped_rows) > 5:
                self.logger.warning(f"  ... and {len(skipped_rows) - 5} more")

        if not valid_rows:
            self.logger.error("No valid rows found in CSV. Exiting.")
            return 1

        self.logger.info(f"Processing {len(valid_rows)} valid rows")

        # Initialize LLM and Email components
        ollama_client = OllamaClient(
            base_url=self.config.get("ollama", {}).get("base_url", "http://localhost:11434"),
            model=self.config.get("ollama", {}).get("model", "llama3"),
            timeout_seconds=self.config.get("ollama", {}).get("timeout_seconds", 30),
            max_retries=self.config.get("ollama", {}).get("max_retries", 3)
        )

        email_generator = EmailGenerator(
            resume_json_path=self.config.get("resume", {}).get("json_path", "resume/resume.json"),
            ollama_client=ollama_client
        )

        test_mode = self.config.get("email_processing", {}).get("test_mode", False)
        dry_run = self.config.get("email_processing", {}).get("dry_run", False)

        email_sender = None
        if not dry_run:
            email_sender = EmailSenderFactory.create_sender(self.config, test_mode=test_mode)
            if not email_sender and not test_mode:
                self.logger.error("Failed to initialize email sender. Check Gmail credentials.")
                return 1

        # Process each row
        stats = {
            "sent": 0,
            "failed": 0,
            "skipped": len(skipped_rows),
            "errors": []
        }

        output_csv_path = self._get_output_csv_path(csv_filename)
        csv_results = []

        for row_idx, row in enumerate(valid_rows):
            try:
                email = row["email"]
                description = row["description"]

                self.logger.info(f"[{row_idx + 1}/{len(valid_rows)}] Processing {email}")

                # Generate email
                skip_llm = self.config.get("email_processing", {}).get("skip_llm", False)
                email_content = email_generator.generate_email(
                    description,
                    use_llm=not skip_llm,
                    skip_llm_on_error=True
                )

                subject = email_content.get("subject", "Application")
                body = email_content.get("body", "")

                # Preview mode: print and ask for confirmation
                if hasattr(args, 'preview') and args.preview and row_idx == 0:
                    print("\n" + "="*80)
                    print("PREVIEW EMAIL")
                    print("="*80)
                    print(f"\nTo: {email}")
                    print(f"Subject: {subject}")
                    print(f"\nBody:\n{body}")
                    print("\n" + "="*80)
                    user_input = input("\nProceed to send emails? (yes/no): ").strip().lower()
                    if user_input not in ['yes', 'y']:
                        self.logger.info("User cancelled. Exiting.")
                        return 0

                # Log preview in dry-run mode
                if dry_run:
                    # Print full context
                    print("\n" + "="*80)
                    print("DRY-RUN: EMAIL GENERATION DETAILS")
                    print("="*80)
                    print(f"\n📧 Recipient Email: {email}")
                    print(f"\n📄 JOB DESCRIPTION FROM CSV:")
                    print("─"*80)
                    print(description)
                    print("─"*80)
                    print(f"\n✉️  GENERATED EMAIL:")
                    print("="*80)
                    print(f"To: {email}")
                    print(f"Subject: {subject}")
                    print(f"\n{'─'*80}")
                    print("BODY:")
                    print(f"{'─'*80}\n")
                    print(body)
                    print(f"\n{'─'*80}")
                    print("="*80 + "\n")
                    
                    self.logger.info(f"[DRY-RUN] Would send to {email}: {subject}")
                    csv_results.append({
                        **row["raw_data"],
                        "sent_status": "DRY-RUN",
                        "sent_at": "",
                        "message_id": "",
                        "error": ""
                    })
                    continue

                # Send email
                if test_mode or email_sender:
                    success, message_id = email_sender.send_email(email, subject, body)

                    if success:
                        self.logger.info(f"✓ Email sent to {email} (ID: {message_id})")
                        csv_reader.add_sent_email(email, message_id, description)
                        stats["sent"] += 1

                        csv_results.append({
                            **row["raw_data"],
                            "sent_status": "success",
                            "sent_at": datetime.now().isoformat(),
                            "message_id": message_id,
                            "error": ""
                        })
                    else:
                        self.logger.error(f"✗ Failed to send to {email}: {message_id}")
                        stats["failed"] += 1
                        stats["errors"].append({"email": email, "reason": message_id})

                        csv_results.append({
                            **row["raw_data"],
                            "sent_status": "failed",
                            "sent_at": "",
                            "message_id": "",
                            "error": message_id
                        })

            except Exception as e:
                self.logger.error(f"✗ Unexpected error processing {email}: {e}")
                stats["failed"] += 1
                stats["errors"].append({"email": email, "reason": str(e)})

                csv_results.append({
                    **row["raw_data"],
                    "sent_status": "failed",
                    "sent_at": "",
                    "message_id": "",
                    "error": str(e)
                })

        # Write results to output CSV
        self._write_output_csv(output_csv_path, csv_results, valid_rows[0]["raw_data"].keys())

        # Print summary
        self._print_summary(stats, len(valid_rows))

        return 0 if stats["failed"] == 0 else 1

    def _apply_cli_overrides(self, args):
        """Override config with CLI arguments."""
        if args.dry_run:
            self.config["email_processing"]["dry_run"] = True

        self.logger.info(f"Config loaded from: {args.config}")

    def _run_preflight_checks(self, csv_filename: str) -> bool:
        """Run all pre-flight validation checks."""
        self.logger.info("Running pre-flight checks...")

        validator = PreflightValidator(self.config)

        # Always validate resume and paths
        all_valid, errors = validator.validate_all()
        if not all_valid:
            for error in errors:
                self.logger.error(f"  ✗ {error}")
            return False

        # Check CSV file
        is_valid, msg = validator.validate_csv_file(csv_filename)
        if not is_valid:
            self.logger.error(f"  ✗ {msg}")
            return False

        # Check Ollama unless skip_llm is set
        if not self.config.get("email_processing", {}).get("skip_llm", False):
            is_valid, msg = validator.validate_ollama_connectivity()
            if not is_valid:
                self.logger.error(f"  ✗ {msg}")
                if not self.config.get("email_processing", {}).get("dry_run", False):
                    return False

        # Check Gmail unless dry-run or test-mode
        is_test_mode = self.config.get("email_processing", {}).get("test_mode", False)
        is_dry_run = self.config.get("email_processing", {}).get("dry_run", False)
        if not is_dry_run and not is_test_mode:
            is_valid, msg = validator.validate_gmail_credentials()
            if not is_valid:
                self.logger.error(f"  ✗ {msg}")
                return False

        self.logger.info("✓ All pre-flight checks passed")
        return True

    def _get_output_csv_path(self, input_filename: str) -> Path:
        """Get output CSV path with timestamp."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = Path(self.config.get("file_paths", {}).get("output_dir", "logs"))
        output_dir.mkdir(parents=True, exist_ok=True)

        base_name = Path(input_filename).stem
        return output_dir / f"{base_name}_results_{timestamp}.csv"

    def _write_output_csv(self, output_path: Path, results: List[Dict], original_headers: List[str]):
        """Write results to output CSV with status columns."""
        if not results:
            self.logger.warning("No results to write")
            return

        # Add status columns if not present
        status_headers = ["sent_status", "sent_at", "message_id", "error"]

        try:
            with open(output_path, "w", newline="", encoding="utf-8") as f:
                fieldnames = list(original_headers) + status_headers
                writer = csv.DictWriter(f, fieldnames=fieldnames)

                writer.writeheader()
                for result in results:
                    # Ensure all fields exist
                    row = {field: result.get(field, "") for field in fieldnames}
                    writer.writerow(row)

            self.logger.info(f"Results written to {output_path}")
        except Exception as e:
            self.logger.error(f"Failed to write output CSV: {e}")

    def _print_summary(self, stats: Dict[str, Any], total_valid: int):
        """Print final summary."""
        summary = f"""
{'=' * 80}
EXECUTION SUMMARY
{'=' * 80}
Total Rows:       {total_valid + stats['skipped']}
Valid Rows:       {total_valid}
Skipped Rows:     {stats['skipped']}
Emails Sent:      {stats['sent']}
Failed:           {stats['failed']}
Success Rate:     {(stats['sent'] / total_valid * 100):.1f}% if total_valid > 0 else 0%
{'=' * 80}
"""
        self.logger.info(summary)

        if stats["errors"]:
            self.logger.warning(f"Failed emails ({len(stats['errors'])}):")
            for error in stats["errors"][:5]:
                self.logger.warning(f"  - {error['email']}: {error['reason']}")
            if len(stats["errors"]) > 5:
                self.logger.warning(f"  ... and {len(stats['errors']) - 5} more")


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

    return parser.parse_args()


def main():
    """Main entry point."""
    args = parse_arguments()

    # Check for .env file
    env_path = Path(".env")
    if not env_path.exists():
        from dotenv import load_dotenv
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
