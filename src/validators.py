"""
Validators module for SmartApply.
Pre-flight checks to ensure all resources are available before processing.
"""

import logging
import os
from pathlib import Path
from typing import Dict, Any, List, Tuple

logger = logging.getLogger(__name__)


class PreflightValidator:
    """Perform pre-flight validation checks."""

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize validator with config.
        
        Args:
            config: Configuration dictionary
        """
        self.config = config

    def validate_all(self) -> Tuple[bool, List[str]]:
        """
        Run all validation checks.
        
        Returns:
            Tuple of (all_valid: bool, errors: List[str])
        """
        errors = []

        # Check resume files
        resume_errors = self.validate_resume_files()
        errors.extend(resume_errors)

        # Check input directory
        input_errors = self.validate_input_directory()
        errors.extend(input_errors)

        # Check file permissions and paths
        path_errors = self.validate_file_paths()
        errors.extend(path_errors)

        if errors:
            logger.error(f"Pre-flight validation failed with {len(errors)} error(s)")
            return False, errors
        else:
            logger.info("All pre-flight checks passed")
            return True, []

    def validate_resume_files(self) -> List[str]:
        """Check if resume files exist and are readable."""
        errors = []

        resume_config = self.config.get("resume", {})
        resume_dir = Path("resume")
        
        # Auto-detect JSON file if not specified
        resume_json = resume_config.get("json_path")
        if not resume_json:
            json_files = list(resume_dir.glob("*.json"))
            if json_files:
                resume_json = str(json_files[0])
                logger.info(f"Auto-detected resume JSON: {resume_json}")
            else:
                error = "No resume JSON file found in resume/ directory"
                logger.error(error)
                errors.append(error)
        
        # Auto-detect PDF file if not specified
        resume_pdf = resume_config.get("pdf_path")
        if not resume_pdf:
            pdf_files = list(resume_dir.glob("*.pdf"))
            if pdf_files:
                resume_pdf = str(pdf_files[0])
                logger.info(f"Auto-detected resume PDF: {resume_pdf}")
            else:
                error = "No resume PDF file found in resume/ directory"
                logger.error(error)
                errors.append(error)
        
        # Validate found JSON file
        if resume_json:
            json_path = Path(resume_json)
            if not json_path.exists():
                error = f"Resume JSON not found: {resume_json}"
                logger.error(error)
                errors.append(error)
            elif not json_path.is_file():
                error = f"Resume JSON is not a file: {resume_json}"
                logger.error(error)
                errors.append(error)
            else:
                logger.info(f"✓ Resume JSON found: {resume_json}")

        # Validate found PDF file
        if resume_pdf:
            pdf_path = Path(resume_pdf)
            if not pdf_path.exists():
                error = f"Resume PDF not found: {resume_pdf}"
                logger.error(error)
                errors.append(error)
            elif not pdf_path.is_file():
                error = f"Resume PDF is not a file: {resume_pdf}"
                logger.error(error)
                errors.append(error)
            else:
                # Check if PDF is readable
                try:
                    with open(pdf_path, "rb") as f:
                        f.read(4)  # Read first 4 bytes
                    logger.info(f"✓ Resume PDF found and readable: {resume_pdf}")
                except Exception as e:
                    error = f"Resume PDF is not readable: {e}"
                    logger.error(error)
                    errors.append(error)

        return errors

    def validate_input_directory(self) -> List[str]:
        """Check if input directory exists and is accessible."""
        errors = []

        input_dir = self.config.get("file_paths", {}).get("input_dir", "input")
        input_path = Path(input_dir)

        if not input_path.exists():
            error = f"Input directory does not exist: {input_dir}"
            logger.error(error)
            errors.append(error)
        elif not input_path.is_dir():
            error = f"Input path is not a directory: {input_dir}"
            logger.error(error)
            errors.append(error)
        else:
            logger.info(f"✓ Input directory found: {input_dir}")

        return errors

    def validate_file_paths(self) -> List[str]:
        """Check if file paths are valid and create directories if needed."""
        errors = []

        file_paths = self.config.get("file_paths", {})

        # Check output/logs directory
        output_dir = file_paths.get("output_dir", "logs")
        output_path = Path(output_dir)

        try:
            output_path.mkdir(parents=True, exist_ok=True)
            logger.info(f"✓ Output directory ready: {output_dir}")
        except Exception as e:
            error = f"Cannot create output directory {output_dir}: {e}"
            logger.error(error)
            errors.append(error)

        # Check data directory for tracking
        data_dir = Path(file_paths.get("sent_emails_db", "data/sent_emails.json")).parent
        try:
            data_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"✓ Data directory ready: {data_dir}")
        except Exception as e:
            error = f"Cannot create data directory {data_dir}: {e}"
            logger.error(error)
            errors.append(error)

        return errors

    def validate_ollama_connectivity(self) -> Tuple[bool, str]:
        """Check if Ollama is running and accessible."""
        try:
            from src.services import OllamaService

            ollama_config = self.config.get("ollama", {})
            service = OllamaService(
                base_url=ollama_config.get("base_url", "http://localhost:11434"),
                model=ollama_config.get("model", "llama3")
            )

            if service.is_available():
                logger.info(f"✓ Ollama is available at {service.base_url} with model '{service.model}'")
                return True, "Ollama is available"
            else:
                error = f"Ollama is not responding at {service.base_url}"
                logger.error(error)
                return False, error

        except Exception as e:
            error = f"Failed to check Ollama connectivity: {e}"
            logger.error(error)
            return False, error

    def validate_gmail_credentials(self) -> Tuple[bool, str]:
        """Check if Gmail credentials are valid."""
        # Anchor to project root (parent of src/) so paths work regardless of CWD
        project_root = Path(__file__).resolve().parent.parent

        # Precedence: 
        # 1. Environment Variable (may have been set by orchestrator for --user)
        # 2. Config (explicitly set via --user or config.yaml)
        # 3. Default auto-detection in project root
        credentials_path = os.getenv("GMAIL_API_CREDENTIALS_PATH") or self.config.get("gmail", {}).get("credentials_path")
        
        if not credentials_path:
            json_files = list(project_root.glob("*.json"))
            if json_files:
                credentials_path = str(json_files[0])
                logger.info(f"Auto-detected credentials JSON in root: {credentials_path}")
            else:
                error = "No credentials JSON file found in project root or environment"
                logger.error(error)
                return False, error

        # Resolve to absolute path for the check
        abs_cred_path = Path(credentials_path)
        if not abs_cred_path.is_absolute():
             abs_cred_path = project_root / credentials_path

        if not abs_cred_path.exists():
            error = f"Gmail API credentials not found at: {abs_cred_path}"
            logger.error(error)
            return False, error

        # Store resolved absolute path back into config for other services
        self.config.setdefault("gmail", {})["credentials_path"] = str(abs_cred_path)

        # Auto-detect resume PDF by extension
        resume_pdf_path = self.config.get("resume", {}).get("pdf_path")
        if not resume_pdf_path:
            resume_dir = Path("resume")
            pdf_files = list(resume_dir.glob("*.pdf")) if resume_dir.exists() else []
            if pdf_files:
                resume_pdf_path = str(pdf_files[0])
                logger.info(f"Auto-detected resume PDF: {resume_pdf_path}")
            else:
                error = "No resume PDF file found in resume/ directory"
                logger.error(error)
                return False, error

        try:
            from src.services import GmailAPISender

            sender = GmailAPISender(
                credentials_path=credentials_path,
                resume_pdf_path=resume_pdf_path,
                test_mode=False
            )

            is_valid, msg = sender.validate_credentials()
            if is_valid:
                logger.info(f"✓ Gmail credentials validated")
                return True, msg
            else:
                logger.error(f"✗ Gmail validation failed: {msg}")
                return False, msg

        except Exception as e:
            error = f"Failed to validate Gmail credentials: {e}"
            logger.error(error)
            return False, error

    def validate_csv_file(self, csv_filename: str) -> Tuple[bool, str]:
        """Check if specified CSV file exists and is readable."""
        input_dir = self.config.get("file_paths", {}).get("input_dir", "input")
        csv_path = Path(input_dir) / csv_filename

        if not csv_path.exists():
            error = f"CSV file not found: {csv_path}"
            logger.error(error)
            return False, error

        if not csv_path.is_file():
            error = f"CSV path is not a file: {csv_path}"
            logger.error(error)
            return False, error

        try:
            with open(csv_path, "r") as f:
                f.read(1)  # Try to read first byte
            logger.info(f"✓ CSV file found and readable: {csv_filename}")
            return True, "CSV file is valid"
        except Exception as e:
            error = f"CSV file is not readable: {e}"
            logger.error(error)
            return False, error
