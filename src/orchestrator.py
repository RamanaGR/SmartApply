"""
SmartApply Orchestrator - Main orchestration logic for email automation pipeline.
Coordinates between CSV reading, LLM generation, email validation, and Gmail sending.
"""

import csv
import json
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, Future
from datetime import datetime, date
from pathlib import Path
from typing import Dict, List, Any, Optional

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config_loader import load_config
from src.services import CSVService, OllamaService, EmailGeneratorService, EmailValidatorService, GmailAPISender
from src.models import AppConfig
from src.core import ResumeHandler
from src.validators import PreflightValidator


logger = logging.getLogger(__name__)


class SmartApplyOrchestrator:
    """Main orchestrator for the email automation pipeline."""

    def __init__(self, config_file: Optional[str] = None):
        """Initialize orchestrator with configuration."""
        self.config_loader = load_config(config_file)
        self.config = self.config_loader.to_dict()
        self._setup_logging()
        self.dry_run = False
        self.logger = logging.getLogger(__name__)

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
                logging.FileHandler(app_log, encoding='utf-8'),
                logging.StreamHandler(sys.stdout)
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

        # Load resume (auto-detect JSON by extension if not configured)
        resume_json_path = self.config.get("resume", {}).get("json_path")
        if not resume_json_path:
            resume_dir = Path("resume")
            json_files = list(resume_dir.glob("*.json")) if resume_dir.exists() else []
            if json_files:
                resume_json_path = str(json_files[0])
                self.logger.info(f"Auto-detected resume JSON: {resume_json_path}")
            else:
                self.logger.error("No resume JSON file found in resume/ directory")
                return 1

        try:
            resume = ResumeHandler.load_resume(resume_json_path)
            user_name = resume.data.name
        except Exception as e:
            self.logger.error(f"Failed to load resume: {e}")
            return 1

        # Ensure sanitized_user is available for log and output filenames
        sanitized_user = "".join(c for c in user_name if c.isalnum() or c in (' ', '-', '_')).strip().replace(' ', '_').lower()
        if not sanitized_user:
            sanitized_user = "user"

        default_db_path = Path("data/sent_emails.json")
        configured_db = self.config.get("file_paths", {}).get("sent_emails_db", str(default_db_path))
        
        # Use a common database file for all users
        db_path = Path(configured_db)

        # Get column mapping from config (merged with any overrides)
        column_mapping = self.config.get("input", {}).get("column_mapping", {})

        # Load CSV
        csv_service = CSVService(
            input_dir=self.config.get("file_paths", {}).get("input_dir", "input"),
            sent_emails_db=str(db_path),
            column_mapping=column_mapping,
            dry_run=self.dry_run
        )

        try:
            valid_rows, skipped_rows = csv_service.read_csv(
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


        # Initialize LLM service
        ollama_service = OllamaService(
            base_url=self.config.get("ollama", {}).get("base_url", "http://localhost:11434"),
            model=self.config.get("ollama", {}).get("model", "llama3"),
            timeout_seconds=self.config.get("ollama", {}).get("timeout_seconds", 30),
            max_retries=self.config.get("ollama", {}).get("max_retries", 3)
        )

        # Initialize services
        email_generator = EmailGeneratorService(
            resume_data=resume.data,
            user_name=user_name,
            ollama_service=ollama_service
        )
        email_validator = EmailValidatorService()

        test_mode = self.config.get("email_processing", {}).get("test_mode", False)
        dry_run = self.config.get("email_processing", {}).get("dry_run", False)

        email_sender = None
        if not dry_run:
            # Auto-detect credentials JSON by extension if not configured
            creds_path = self.config.get("gmail", {}).get("credentials_path")
            if not creds_path:
                cred_files = list(Path(".").glob("*.json"))
                creds_path = str(cred_files[0]) if cred_files else "credentials.json"

            # Auto-detect resume PDF by extension if not configured
            resume_pdf = self.config.get("resume", {}).get("pdf_path")
            if not resume_pdf:
                resume_dir = Path("resume")
                pdf_files = list(resume_dir.glob("*.pdf")) if resume_dir.exists() else []
                resume_pdf = str(pdf_files[0]) if pdf_files else "resume/resume.pdf"

            email_sender = GmailAPISender(
                credentials_path=creds_path,
                resume_pdf_path=resume_pdf,
                email_delay_min_seconds=self.config.get("gmail", {}).get("email_delay_min_seconds", 30),
                email_delay_max_seconds=self.config.get("gmail", {}).get("email_delay_max_seconds", 60),
                cooldown_every_n_emails=self.config.get("gmail", {}).get("cooldown_every_n_emails", 10),
                cooldown_min_seconds=self.config.get("gmail", {}).get("cooldown_min_seconds", 180),
                cooldown_max_seconds=self.config.get("gmail", {}).get("cooldown_max_seconds", 300),
                test_mode=test_mode
            )
            
            # Verify email_sender is initialized
            if email_sender.service is None and not test_mode:
                self.logger.error("Gmail API service failed to initialize. Cannot send emails.")
                return 1

        # Process each row
        stats: Dict[str, Any] = {
            "sent": 0,
            "failed": 0,
            "skipped": len(skipped_rows),
            "errors": []
        }

        output_csv_path = self._get_output_csv_path(csv_filename, user_name)
        csv_results: List[Dict[str, Any]] = []

        # --- Daily Cap Check ---
        daily_cap = self.config.get("email_processing", {}).get("daily_cap", 100)
        if not dry_run:
            sent_today = self._count_sent_today()
            remaining_cap = daily_cap - sent_today
            if remaining_cap <= 0:
                self.logger.warning(f"🚫 Daily cap of {daily_cap} emails reached ({sent_today} sent today). Stopping.")
                return 0
            if remaining_cap < len(valid_rows):
                self.logger.warning(f"⚠️  Daily cap: {remaining_cap} emails remaining today (cap={daily_cap}, sent={sent_today}). Trimming batch.")
                valid_rows = valid_rows[:remaining_cap]

        # --- LLM Config ---
        llm_timeout = self.config.get("ollama", {}).get("timeout_seconds", 40)
        llm_retry_timeout = self.config.get("ollama", {}).get("retry_timeout_seconds", 12)
        llm_minimal_timeout = self.config.get("ollama", {}).get("minimal_timeout_seconds", 8)
        llm_quality_retries = self.config.get("ollama", {}).get("llm_quality_retries", 3)
        skip_llm = self.config.get("email_processing", {}).get("skip_llm", False)

        def _generate_for_row(row: Dict) -> Any:
            """Generate email for a single row (runs in background thread for prefetch)."""
            _email = row["email"]
            _title = row.get("title", "")
            _description = row["description"]
            _company = row.get("raw_data", {}).get("Company", "").strip()
            _contact_info = row.get("raw_data", {}).get("Contact Info", "").strip()
            _job_context = f"{_title}\n{_description}".strip() if _title else _description
            return email_generator.generate(
                job_description=_job_context,
                recipient_email=_email,
                use_llm=not skip_llm,
                skip_llm_on_error=True,
                company_from_csv=_company,
                contact_info=_contact_info,
                job_title=_title,
                timeout_seconds=llm_timeout,
                retry_timeout_seconds=llm_retry_timeout,
                minimal_timeout_seconds=llm_minimal_timeout,
                max_quality_retries=llm_quality_retries,
            )

        # --- LLM Prefetch Pipeline ---
        # Pre-generate email #0 before the loop.
        # The NEXT email's generation is kicked off AFTER user confirmation (Y/N),
        # so background log messages don't pollute the input() prompt.
        # During the Gmail send delay (30-60s), the next email generates in parallel.
        with ThreadPoolExecutor(max_workers=1) as executor:
            next_email_future: Future = executor.submit(_generate_for_row, valid_rows[0]) if valid_rows else None

            for row_idx, row in enumerate(valid_rows):
                try:
                    email = row["email"]
                    title = row.get("title", "")
                    description = row["description"]
                    # Get company from raw CSV data (the CSV has it as "Company" with capital C)
                    company = row.get("raw_data", {}).get("Company", "").strip()

                    # Get contact info DIRECTLY from CSV "Contact Info" column (not from Payload)
                    contact_info = row.get("raw_data", {}).get("Contact Info", "").strip()

                    self.logger.info(f"[{row_idx + 1}/{len(valid_rows)}] Processing {email} (Company: {company})")

                    # --- Prefetch: get the pre-generated email from the background thread ---
                    self.logger.info(f"  ⏳ Waiting for LLM generation to complete...")
                    email_obj = next_email_future.result()
                    # NOTE: We do NOT start the next prefetch here - we wait until AFTER
                    # the user answers Y/N to avoid log messages polluting the input() prompt.

                    # Validate email content
                    validation_result = email_validator.validate(email_obj.subject, email_obj.body)

                    if validation_result.errors:
                        self.logger.error(f"✗ Email validation failed for {email}:")
                        for error in validation_result.errors:
                            self.logger.error(f"  - {error}")
                        stats["failed"] += 1
                        csv_results.append({
                            **row["raw_data"],
                            "sent_status": "validation_failed",
                            "sent_at": "",
                            "message_id": "",
                            "error": "; ".join(validation_result.errors)
                        })
                        continue

                    # Log warnings
                    if validation_result.warnings:
                        for warning in validation_result.warnings:
                            self.logger.warning(f"⚠ {warning}")

                    # Log preview in dry-run mode
                    if dry_run:
                        # Print full context
                        print("\n" + "="*80)
                        print("DRY-RUN: EMAIL GENERATION DETAILS")
                        print("="*80)
                        print(f"\n📧 Recipient Email: {email}")
                        if title:
                            print(f"\n📋 JOB TITLE FROM CSV:")
                            print("─"*80)
                            print(title)
                            print("─"*80)
                        print(f"\n📄 JOB DESCRIPTION FROM CSV:")
                        print("─"*80)
                        print(description)
                        print("─"*80)
                        print(f"\n✉️  GENERATED EMAIL:")
                        print("="*80)
                        print(f"To: {email}")
                        print(f"Subject: {email_obj.subject}")
                        print(f"\n{'─'*80}")
                        print("BODY:")
                        print(f"{'─'*80}\n")
                        print(email_obj.body)
                        print(f"\n{'─'*80}")
                        print("="*80 + "\n")

                        self.logger.info(f"[DRY-RUN] Would send to {email}: {email_obj.subject}")
                        csv_results.append({
                            **row["raw_data"],
                            "sent_status": "DRY-RUN",
                            "sent_at": "",
                            "message_id": "",
                            "error": ""
                        })
                        continue

                    # Send email
                    if test_mode or (not dry_run and email_sender):
                        # Ask for user confirmation before sending (unless dry-run)
                        user_confirmation_enabled = self.config.get("email_processing", {}).get("user_confirmation_before_send", True)

                        if user_confirmation_enabled:
                            print("\n" + "="*80)
                            print(f"EMAIL #{row_idx + 1}/{len(valid_rows)} - CONFIRMATION REQUIRED")
                            print("="*80)
                            print(f"\nTo: {email}")
                            print(f"Subject: {email_obj.subject}")
                            print(f"\nBody:\n{email_obj.body}")
                            print("\n" + "="*80)

                            # Temporarily silence the stream logger so background
                            # threads don't pollute the input() prompt
                            stream_handlers = [h for h in logging.root.handlers
                                               if isinstance(h, logging.StreamHandler)
                                               and not isinstance(h, logging.FileHandler)]
                            for h in stream_handlers:
                                h.setLevel(logging.CRITICAL)

                            while True:
                                user_input = input(f"\nSend this email to {email}? (Y/N): ").strip().upper()
                                if user_input in ['Y', 'N', 'YES', 'NO']:
                                    break
                                print("Please enter Y or N")

                            # Restore stream logger level
                            for h in stream_handlers:
                                h.setLevel(logging.DEBUG)

                            # --- Prefetch: NOW kick off next email generation (after Y/N answered) ---
                            # This runs during the Gmail send delay (30-60s) below.
                            if row_idx + 1 < len(valid_rows):
                                next_email_future = executor.submit(_generate_for_row, valid_rows[row_idx + 1])

                            if user_input not in ['Y', 'YES']:
                                self.logger.info(f"User skipped sending to {email}")
                                csv_results.append({
                                    **row["raw_data"],
                                    "sent_status": "user_skipped",
                                    "sent_at": "",
                                    "message_id": "",
                                    "error": "User declined to send"
                                })
                                continue

                        else:
                            # No confirmation needed — start prefetch immediately after getting current email
                            if row_idx + 1 < len(valid_rows):
                                next_email_future = executor.submit(_generate_for_row, valid_rows[row_idx + 1])

                        # Send email (Gmail delay + cooldown handled inside send_email)
                        if email_sender:
                            success, message_id = email_sender.send_email(email, email_obj.subject, email_obj.body)

                            if success:
                                self.logger.info(f"✓ Email sent to {email} (ID: {message_id})")
                                csv_service.add_sent_email(email, message_id, description)
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
                        else:
                            error_msg = "Email sender not initialized"
                            self.logger.error(f"✗ Cannot send to {email}: {error_msg}")
                            stats["failed"] += 1

                            csv_results.append({
                                **row["raw_data"],
                                "sent_status": "failed",
                                "sent_at": "",
                                "message_id": "",
                                "error": error_msg
                            })
                    else:
                        # No email sender available
                        self.logger.info(f"[SKIPPED] {email} (no email sender in dry_run or test mode)")
                        csv_results.append({
                            **row["raw_data"],
                            "sent_status": "skipped",
                            "sent_at": "",
                            "message_id": "",
                            "error": "Dry-run or test mode enabled"
                        })

                except Exception as e:
                    self.logger.error(f"✗ Unexpected error processing row {row_idx + 1}: {e}")
                    stats["failed"] += 1
                    stats["errors"].append({"row": row_idx + 1, "reason": str(e)})

                    csv_results.append({
                        **row.get("raw_data", {}),
                        "sent_status": "failed",
                        "sent_at": "",
                        "message_id": "",
                        "error": str(e)
                    })



        # Write results to output CSV and HTML
        self._write_output_csv(output_csv_path, csv_results, valid_rows[0]["raw_data"].keys())
        sanitized_user = "".join(c for c in user_name if c.isalnum() or c in (' ', '-', '_')).strip().replace(' ', '_').lower()
        if not sanitized_user:
            sanitized_user = "user"
        self._write_output_html(output_csv_path.parent, f"{sanitized_user}_emails_applied", datetime.now().strftime("%Y%m%d_%H%M%S"), csv_results, stats)

        # Print summary
        self._print_summary(stats, len(valid_rows))

        return 0 if stats["failed"] == 0 else 1

    def _count_sent_today(self) -> int:
        """Count how many emails have been sent today from sent_emails.json."""
        sent_db_path = Path(self.config.get("file_paths", {}).get("sent_emails_db", "data/sent_emails.json"))
        if not sent_db_path.exists():
            return 0
        try:
            with open(sent_db_path, "r") as f:
                data = json.load(f)
            today_str = date.today().isoformat()
            sent_emails = data.get("sent_emails", {})
            count = sum(
                1 for v in sent_emails.values()
                if isinstance(v, dict) and v.get("timestamp", "").startswith(today_str)
            )
            self.logger.info(f"📊 Daily cap check: {count} emails sent today")
            return count
        except Exception as e:
            self.logger.warning(f"Could not read sent_emails.json for daily cap check: {e}")
            return 0

    def _apply_cli_overrides(self, args):
        """Override config with CLI arguments."""
        self.dry_run = getattr(args, 'dry_run', False)
        if self.dry_run:
            if "email_processing" not in self.config:
                self.config["email_processing"] = {}
            self.config["email_processing"]["dry_run"] = True

        if hasattr(args, 'user') and args.user:
            # Anchor to project root (parent of src/) so paths work regardless of CWD
            project_root = Path(__file__).resolve().parent.parent
            user_dir = project_root / "resume" / args.user
            if user_dir.exists():
                self.logger.info(f"Running for user: {args.user} - loading files from resume\\{args.user}")

                # Find credentials.json
                cred_path = user_dir / "credentials.json"
                if cred_path.exists():
                    # EXPLICIT OVERRIDE: Set in config and ALSO set as env var 
                    # so validators.py (which might check os.getenv) sees it too.
                    abs_cred_path = str(cred_path.resolve())
                    self.config.setdefault("gmail", {})["credentials_path"] = abs_cred_path
                    os.environ["GMAIL_API_CREDENTIALS_PATH"] = abs_cred_path
                else:
                    self.logger.warning(f"credentials.json not found in {user_dir}")

                # Find Resume JSON (any json that is not credentials or token)
                json_files = [f for f in user_dir.glob("*.json") if f.name != "credentials.json" and "token" not in f.name]
                if json_files:
                    self.config.setdefault("resume", {})["json_path"] = str(json_files[0].resolve())

                # Find Resume PDF
                pdf_files = list(user_dir.glob("*.pdf"))
                if pdf_files:
                    self.config.setdefault("resume", {})["pdf_path"] = str(pdf_files[0].resolve())
            else:
                self.logger.warning(f"User directory resume\\{args.user} not found. Falling back to global defaults.")


        self.logger.info(f"Config loaded from: {getattr(args, 'config', 'config.yaml')}")

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

    def _get_output_csv_path(self, input_filename: str, user_name: str) -> Path:
        """Get output CSV path with timestamp and prefix."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = Path(self.config.get("file_paths", {}).get("output_dir", "logs"))
        output_dir.mkdir(parents=True, exist_ok=True)

        sanitized_user = "".join(c for c in user_name if c.isalnum() or c in (' ', '-', '_')).strip().replace(' ', '_').lower()
        if not sanitized_user:
            sanitized_user = "user"
        return output_dir / f"{sanitized_user}_emails_applied_results_{timestamp}.csv"

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

    def _write_output_html(self, output_dir: Path, base_name: str, timestamp: str, results: List[Dict], stats: Dict):
        """Write a formatted HTML report summarizing success, skips, and failures."""
        if not results:
            return

        html_path = output_dir / f"{base_name}_report_{timestamp}.html"
        success_rate = (stats["sent"] / len(results) * 100) if results else 0
        
        # Build Table rows dynamically
        rows_html = ""
        for r in results:
            status = r.get("sent_status", "unknown")
            color = "#10b981" if status == "success" else "#f59e0b" if status in ["skipped", "user_skipped"] else "#ef4444"
            email = r.get("Contact Info", "") or r.get("contact_email", "") or "Unknown"
            
            rows_html += f"""
            <tr style="border-bottom: 1px solid #e5e7eb;">
                <td style="padding: 12px;">{r.get('Company', 'N/A')}</td>
                <td style="padding: 12px;">{email}</td>
                <td style="padding: 12px;"><span style="background: {color}; color: white; padding: 4px 8px; border-radius: 9999px; font-size: 0.8em; font-weight: bold;">{status.upper()}</span></td>
                <td style="padding: 12px; color: #6b7280; font-size: 0.9em;">{r.get('error', '')}</td>
            </tr>"""

        # Build full HTML
        html_content = f"""<!DOCTYPE html>
<html>
<head>
    <title>SmartApply Execution Report</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; background-color: #f9fafb; color: #111827; padding: 40px; margin: 0; }}
        .container {{ max-width: 1000px; margin: 0 auto; background: white; padding: 30px; border-radius: 8px; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1); }}
        h1 {{ color: #1f2937; border-bottom: 2px solid #e5e7eb; padding-bottom: 10px; }}
        .metrics {{ display: flex; gap: 20px; margin: 20px 0; }}
        .metric-card {{ background: #f3f4f6; padding: 20px; border-radius: 8px; flex: 1; text-align: center; }}
        .metric-card h3 {{ margin: 0; color: #6b7280; font-size: 0.9rem; text-transform: uppercase; }}
        .metric-card p {{ margin: 10px 0 0 0; font-size: 2rem; font-weight: bold; color: #111827; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 30px; }}
        th {{ background: #f9fafb; padding: 12px; text-align: left; font-weight: 600; color: #374151; border-bottom: 2px solid #e5e7eb; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>SmartApply Run Report</h1>
        <p style="color: #6b7280;">Execution Timestamp: {timestamp}</p>
        
        <div class="metrics">
            <div class="metric-card"><h3>Total Processed</h3><p>{len(results)}</p></div>
            <div class="metric-card"><h3>Sent</h3><p style="color: #10b981;">{stats['sent']}</p></div>
            <div class="metric-card"><h3>Skipped</h3><p style="color: #f59e0b;">{stats['skipped']}</p></div>
            <div class="metric-card"><h3>Failed</h3><p style="color: #ef4444;">{stats['failed']}</p></div>
        </div>

        <table>
            <thead>
                <tr>
                    <th>Company</th>
                    <th>Email</th>
                    <th>Status</th>
                    <th>Details</th>
                </tr>
            </thead>
            <tbody>
                {rows_html}
            </tbody>
        </table>
    </div>
</body>
</html>"""

        try:
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(html_content)
            self.logger.info(f"HTML Report written to {html_path}")
        except Exception as e:
            self.logger.error(f"Failed to write HTML Report: {e}")

    def _print_summary(self, stats: Dict[str, Any], total_valid: int):
        """Print final summary."""
        success_rate = (stats["sent"] / total_valid * 100) if total_valid > 0 else 0
        summary = f"""
{'=' * 80}
EXECUTION SUMMARY
{'=' * 80}
Total Rows:       {total_valid + stats['skipped']}
Valid Rows:       {total_valid}
Skipped Rows:     {stats['skipped']}
Emails Sent:      {stats['sent']}
Failed:           {stats['failed']}
Success Rate:     {success_rate:.1f}%
{'=' * 80}
"""
        self.logger.info(summary)

        if stats["errors"]:
            self.logger.warning(f"Failed emails ({len(stats['errors'])}):")
            for error in stats["errors"][:5]:
                self.logger.warning(f"  - {error['email']}: {error['reason']}")
            if len(stats["errors"]) > 5:
                self.logger.warning(f"  ... and {len(stats['errors']) - 5} more")
