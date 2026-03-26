"""
Email Sender module for SmartApply.
Handles sending emails via Gmail API (OAuth2) with resume attachment and rate limiting.
"""

import logging
import time
import os
import base64
from pathlib import Path
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from typing import Dict, Any, Optional, Tuple

logger = logging.getLogger(__name__)


class GmailAPISender:
    """Send emails via Gmail API (OAuth2) with resume attachment and rate limiting."""

    def __init__(
        self,
        credentials_path: str,
        resume_pdf_path: str,
        email_delay_seconds: float = 0.5,
        test_mode: bool = False
    ):
        """
        Initialize Gmail API sender.
        
        Args:
            credentials_path: Path to credentials.json from Google Cloud Console
            resume_pdf_path: Path to resume PDF to attach
            email_delay_seconds: Delay between sending emails (rate limiting)
            test_mode: If True, logs emails to file instead of sending
        """
        self.credentials_path = credentials_path
        self.resume_pdf_path = Path(resume_pdf_path)
        self.email_delay_seconds = email_delay_seconds
        self.test_mode = test_mode
        self.last_send_time = 0
        self.service = None
        self._init_service()

    def _init_service(self):
        """Initialize Gmail API service."""
        try:
            from google.auth.transport.requests import Request
            from google.oauth2.service_account import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
            from google.auth.transport.requests import Request
            import pickle
            
            SCOPES = ["https://www.googleapis.com/auth/gmail.send"]
            
            creds = None
            
            # Check for saved token
            token_path = Path("token.pickle")
            if token_path.exists():
                with open(token_path, "rb") as token_file:
                    creds = pickle.load(token_file)
            
            # If no valid credentials, get new ones
            if not creds or not creds.valid:
                if creds and creds.expired and creds.refresh_token:
                    creds.refresh(Request())
                else:
                    flow = InstalledAppFlow.from_client_secrets_file(
                        self.credentials_path, SCOPES
                    )
                    creds = flow.run_local_server(port=0)
                
                # Save credentials for next time
                with open(token_path, "wb") as token_file:
                    pickle.dump(creds, token_file)
            
            from googleapiclient.discovery import build
            self.service = build("gmail", "v1", credentials=creds)
            logger.info("Gmail API service initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize Gmail API service: {e}")
            self.service = None

    def send_email(self, recipient_email: str, subject: str, body: str) -> Tuple[bool, str]:
        """
        Send personalized email with resume attachment.
        
        Args:
            recipient_email: Recipient email address
            subject: Email subject
            body: Email body
            
        Returns:
            Tuple of (success: bool, message_id: str or error message)
        """
        # Enforce rate limiting
        time_since_last = time.time() - self.last_send_time
        if time_since_last < self.email_delay_seconds:
            sleep_time = self.email_delay_seconds - time_since_last
            logger.debug(f"Rate limiting: sleeping for {sleep_time:.2f}s")
            time.sleep(sleep_time)

        self.last_send_time = time.time()

        # Test mode: log instead of send
        if self.test_mode:
            return self._test_mode_log(recipient_email, subject, body)

        if not self.service:
            return False, "Gmail API service not initialized"

        # Validate resume PDF exists
        if not self.resume_pdf_path.exists():
            error_msg = f"Resume PDF not found: {self.resume_pdf_path}"
            logger.error(error_msg)
            return False, error_msg

        try:
            # Build email
            msg = self._build_message(recipient_email, subject, body)

            # Send via Gmail API
            message = {"raw": base64.urlsafe_b64encode(msg.as_bytes()).decode()}
            result = self.service.users().messages().send(userId="me", body=message).execute()
            
            message_id = result.get("id", "unknown")
            logger.info(f"Email sent successfully to {recipient_email}. Message ID: {message_id}")
            return True, message_id

        except Exception as e:
            error_msg = f"Failed to send email: {e}"
            logger.error(error_msg)
            return False, error_msg

    def _build_message(self, recipient_email: str, subject: str, body: str) -> MIMEMultipart:
        """Build MIME email message with resume attachment."""
        msg = MIMEMultipart()
        msg["From"] = "me"
        msg["To"] = recipient_email
        msg["Subject"] = subject

        # Add body
        msg.attach(MIMEText(body, "plain"))

        # Attach resume
        if self.resume_pdf_path.exists():
            try:
                with open(self.resume_pdf_path, "rb") as attachment:
                    part = MIMEBase("application", "octet-stream")
                    part.set_payload(attachment.read())
                    encoders.encode_base64(part)
                    part.add_header(
                        "Content-Disposition",
                        f"attachment; filename= {self.resume_pdf_path.name}",
                    )
                    msg.attach(part)
            except Exception as e:
                logger.warning(f"Could not attach resume: {e}")

        return msg

    def validate_credentials(self) -> Tuple[bool, str]:
        """Validate that Gmail credentials are working."""
        try:
            if not self.service:
                return False, "Gmail API service not initialized"
            
            # Try to get user profile
            profile = self.service.users().getProfile(userId="me").execute()
            email = profile.get("emailAddress", "unknown")
            logger.info(f"✓ Gmail credentials validated: {email}")
            return True, f"Connected as {email}"
            
        except Exception as e:
            error_msg = f"Gmail authentication failed: {e}"
            logger.error(error_msg)
            return False, error_msg

    def _test_mode_log(self, recipient_email: str, subject: str, body: str) -> Tuple[bool, str]:
        """Log email instead of sending (test mode)."""
        test_log_path = Path("logs/test_emails.log")
        test_log_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(test_log_path, "a") as f:
            f.write(f"\n{'='*80}\n")
            f.write(f"To: {recipient_email}\n")
            f.write(f"Subject: {subject}\n")
            f.write(f"Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"{'='*80}\n")
            f.write(f"{body}\n")
        
        message_id = f"test_mode_{int(time.time())}"
        logger.info(f"[TEST MODE] Email logged to {test_log_path}: {recipient_email}")
        return True, message_id


class EmailSenderFactory:
    """Factory to create appropriate email sender based on config."""

    @staticmethod
    def create_sender(config: Dict[str, Any], test_mode: bool = False) -> Optional[GmailAPISender]:
        """
        Create email sender from config.
        
        Args:
            config: Configuration dictionary with gmail settings
            test_mode: If True, use test mode
            
        Returns:
            GmailAPISender instance or None if config is invalid
        """
        use_api = config.get("gmail", {}).get("use_api", True)
        
        if not use_api:
            logger.error("SMTP mode is deprecated. Please use Gmail API (use_api: true in config)")
            return None

        # Get credentials path - check .env first, then config, then default
        credentials_path = os.getenv("GMAIL_API_CREDENTIALS_PATH") or config.get("gmail", {}).get("credentials_path") or "credentials.json"
        
        if not Path(credentials_path).exists():
            logger.error(f"Gmail API credentials not found: {credentials_path}")
            logger.error("Download credentials.json from Google Cloud Console and place in project root")
            return None

        resume_pdf = config.get("resume", {}).get("pdf_path", "resume/resume.pdf")
        email_delay = config.get("gmail", {}).get("email_delay_seconds", 0.5)

        return GmailAPISender(
            credentials_path=credentials_path,
            resume_pdf_path=resume_pdf,
            email_delay_seconds=email_delay,
            test_mode=test_mode
        )

