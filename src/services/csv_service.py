"""
CSV reading and processing service for SmartApply.
Handles reading CSV files, validating data, deduplicating entries, and tracking sent emails.
"""

import csv
import json
import logging
import re
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

logger = logging.getLogger(__name__)


class CSVService:
    """Read and validate CSV files with email and job description data."""

    COMMON_EMAIL_COLUMN_VARIANTS = [
        "email", "e-mail", "email_address", "emailaddress",
        "contact", "contact_email", "recipient", "to_address", "contact info"
    ]

    COMMON_DESCRIPTION_COLUMN_VARIANTS = [
        "description", "job_description", "job description",
        "position", "job", "role", "opportunity"
    ]

    def __init__(self, input_dir: str, sent_emails_db: str, column_mapping: Optional[Dict[str, str]] = None, dry_run: bool = False):
        """
        Initialize CSVService.
        
        Args:
            input_dir: Directory containing CSV files
            sent_emails_db: Path to sent_emails.json tracking file
            column_mapping: Optional mapping of logical names to CSV column names
                           e.g., {"email": "Email Address", "description": "Job Description"}
            dry_run: If True, skip duplicate checking
        """
        self.input_dir = Path(input_dir)
        self.sent_emails_db = Path(sent_emails_db)
        self.column_mapping = column_mapping or {}
        self.dry_run = dry_run
        self.sent_emails = self._load_sent_emails()

    def read_csv(self, filename: str, limit: Optional[int] = None) -> Tuple[List[Dict[str, str]], List[Dict[str, str]]]:
        """
        Read and validate CSV file.
        
        Args:
            filename: CSV filename (assumed to be in input_dir)
            limit: Optional limit on number of rows to process
            
        Returns:
            Tuple of (valid_rows, skipped_rows) with row data and skip reason
        """
        csv_path = self.input_dir / filename

        if not csv_path.exists():
            logger.error(f"CSV file not found: {csv_path}")
            raise FileNotFoundError(f"CSV file not found: {csv_path}")

        valid_rows = []
        skipped_rows = []
        seen_emails_in_batch = set()
        row_count = 0

        try:
            with open(csv_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)

                if not reader.fieldnames:
                    raise ValueError("CSV file is empty")

                # Auto-detect or validate email, title and description columns
                email_col, title_col, desc_col = self._detect_columns(reader.fieldnames)

                if not email_col:
                    raise ValueError("Cannot detect email column in CSV. Check column names.")
                if not desc_col:
                    raise ValueError("Description column is required. Cannot detect in CSV.")

                for row_idx, row in enumerate(reader, start=2):  # start=2 because row 1 is header
                    if limit and row_count >= limit:
                        break

                    email = row.get(email_col, "").strip()
                    title = row.get(title_col, "").strip() if title_col else ""
                    title = self._clean_job_title(title)
                    description = row.get(desc_col, "").strip() if desc_col else ""

                    # Extract email if it's in "Email: xxx, Phone: yyy" format
                    email = self._extract_email_from_contact_info(email)

                    skip_reason = self._validate_row(email, title, description, row_idx)
                    if skip_reason:
                        skipped_rows.append({
                            "row": row_idx,
                            "email": email,
                            "reason": skip_reason,
                            "raw_data": row
                        })
                        continue

                    # Check for duplicates (already sent or in current batch) - skip in dry-run mode
                    if not self.dry_run and (self._is_duplicate(email) or email in seen_emails_in_batch):
                        skipped_rows.append({
                            "row": row_idx,
                            "email": email,
                            "reason": "duplicate_or_already_sent",
                            "raw_data": row
                        })
                        continue

                    seen_emails_in_batch.add(email)

                    valid_rows.append({
                        "email": email,
                        "title": title,
                        "description": description,
                        "row_index": row_idx,
                        "raw_data": row
                    })
                    row_count += 1

            logger.info(f"CSV read complete: {len(valid_rows)} valid rows, {len(skipped_rows)} skipped")
            return valid_rows, skipped_rows

        except Exception as e:
            logger.error(f"Error reading CSV {filename}: {e}")
            raise

    def _detect_columns(self, fieldnames: List[str]) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """
        Auto-detect email, title and description columns from CSV headers.
        Respects column_mapping if provided.
        
        Returns:
            Tuple of (email_column, title_column, description_column) or (None, None, None) if not found
        """
        # Normalize fieldnames to lowercase for comparison
        normalized_fields = {name: name for name in fieldnames}
        lowercase_to_original = {name.lower(): name for name in fieldnames}

        # Check column mapping first
        email_col = None
        title_col = None
        desc_col = None

        if "email" in self.column_mapping:
            email_col = self.column_mapping["email"]
        else:
            # Auto-detect email column
            for variant in self.COMMON_EMAIL_COLUMN_VARIANTS:
                for lower_name, original_name in lowercase_to_original.items():
                    if variant.lower() == lower_name:
                        email_col = original_name
                        break
                if email_col:
                    break

        if "title" in self.column_mapping:
            title_col = self.column_mapping["title"]
        else:
            # Auto-detect title column
            for lower_name, original_name in lowercase_to_original.items():
                if "title" in lower_name or "role" in lower_name or "position" in lower_name:
                    title_col = original_name
                    break

        if "description" in self.column_mapping:
            desc_col = self.column_mapping["description"]
        else:
            # Auto-detect description column
            for variant in self.COMMON_DESCRIPTION_COLUMN_VARIANTS:
                for lower_name, original_name in lowercase_to_original.items():
                    if variant.lower() == lower_name:
                        desc_col = original_name
                        break
                if desc_col:
                    break

        logger.debug(f"Detected columns - Email: {email_col}, Title: {title_col}, Description: {desc_col}")
        return email_col, title_col, desc_col

    def _clean_job_title(self, title: str) -> str:
        """
        Sanitize job title to remove junk values commonly scraped from posts.
        Returns empty string if the title is purely visa/contract requirements.
        """
        if not title:
            return ""
            
        t_lower = title.lower()
        
        # Explicit exact matches or substrings that signify garbage titles
        junk_phrases = ["below mentioned", "below mentined", "highlights", "overview", "h1b only", "no gc", "is remote"]
        if any(phrase in t_lower for phrase in junk_phrases):
            return ""
            
        # Check if purely comprised of visa/contract/location terms
        words = [w for w in t_lower.replace('/', ' ').replace('-', ' ').split() if len(w) > 1]
        bad_terms = {
            'c2c', 'w2', '1099', 'h1b', 'gc', 'opt', 'ead', 'remote', 
            'onsite', 'hybrid', 'role', 'position', 'only', 'no', 'please', 
            'is', 'below', 'mentioned'
        }
        
        if words and all(w in bad_terms for w in words):
            return ""
            
        return title.strip()

    def _validate_row(self, email: str, title: str, description: str, row_idx: int) -> Optional[str]:
        """
        Validate a CSV row.
        
        Returns:
            Skip reason if invalid, None if valid
        """
        # CRITICAL: Skip if Description is empty (required for email generation)
        if not description or not description.strip():
            return "missing_or_empty_description"
            
        # Check for AI/ML keywords in title or description
        combined_text = f"{title} {description}"
        if not re.search(r'\b(AI|ML|Artificial Intelligence|Machine Learning)\b', combined_text, re.IGNORECASE):
            return "missing_ai_ml_keywords"
        
        # Validate email
        if not email:
            return "missing_email"

        if not self._is_valid_email(email):
            return f"invalid_email_format"

        return None

    def _is_valid_email(self, email: str) -> bool:
        """Validate email format using regex."""
        pattern = r'^[^\s@]+@[^\s@]+\.[^\s@]+$'
        return bool(re.match(pattern, email))

    def _extract_email_from_contact_info(self, contact_info: str) -> str:
        """Extract email from contact info that may contain 'Email: xxx, Phone: yyy' format."""
        if not contact_info:
            return ""
        
        # Try to find "Email: xxx" pattern
        email_match = re.search(r'Email:\s*([^\s,]+)', contact_info, re.IGNORECASE)
        if email_match:
            return email_match.group(1).strip()
        
        # Try to extract first email-like pattern
        email_pattern_match = re.search(r'[^\s@]+@[^\s@,]+\.[^\s@,]+', contact_info)
        if email_pattern_match:
            return email_pattern_match.group(0).strip()
        
        # Return as-is if no pattern matches
        return contact_info.split(',')[0].strip()

    def _is_duplicate(self, email: str) -> bool:
        """Check if email is already sent or appears multiple times in current batch."""
        return email in self.sent_emails

    def _load_sent_emails(self) -> set:
        """Load set of already sent emails from sent_emails.json."""
        if not self.sent_emails_db.exists():
            return set()

        try:
            with open(self.sent_emails_db, "r") as f:
                data = json.load(f)
                if isinstance(data, dict) and "sent_emails" in data:
                    return set(data["sent_emails"].keys())
                return set()
        except Exception as e:
            logger.warning(f"Failed to load sent_emails.json: {e}. Proceeding with empty set.")
            return set()

    def add_sent_email(self, email: str, message_id: str, job_description: str = ""):
        """Record that an email was sent."""
        self.sent_emails.add(email)
        self._save_sent_emails(email, message_id, job_description)

    def _save_sent_emails(self, email: str, message_id: str, job_description: str = ""):
        """Persist sent email to sent_emails.json."""
        if not self.sent_emails_db.parent.exists():
            self.sent_emails_db.parent.mkdir(parents=True, exist_ok=True)

        try:
            # Load existing data
            if self.sent_emails_db.exists():
                with open(self.sent_emails_db, "r") as f:
                    data = json.load(f)
            else:
                data = {"sent_emails": {}}

            # Add new entry
            from datetime import datetime
            data["sent_emails"][email] = {
                "message_id": message_id,
                "timestamp": datetime.now().isoformat(),
                "job_description_preview": job_description[:100]  # Store first 100 chars for reference
            }

            # Save
            with open(self.sent_emails_db, "w") as f:
                json.dump(data, f, indent=2)

            logger.debug(f"Recorded sent email: {email}")
        except Exception as e:
            logger.error(f"Failed to save sent_emails.json: {e}")
