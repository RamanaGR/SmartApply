"""
Email sending service for SmartApply.
Handles sending emails via Gmail API (OAuth2) with resume attachment and rate limiting.
"""

import logging
import random
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
        email_delay_min_seconds: float = 30.0,
        email_delay_max_seconds: float = 60.0,
        cooldown_every_n_emails: int = 10,
        cooldown_min_seconds: float = 180.0,
        cooldown_max_seconds: float = 300.0,
        test_mode: bool = False
    ):
        """
        Initialize Gmail API sender.
        
        Args:
            credentials_path: Path to credentials.json from Google Cloud Console
            resume_pdf_path: Path to resume PDF to attach
            email_delay_min_seconds: Minimum randomized delay between emails
            email_delay_max_seconds: Maximum randomized delay between emails
            cooldown_every_n_emails: Trigger a long cooldown pause every N emails
            cooldown_min_seconds: Minimum duration of cooldown pause in seconds
            cooldown_max_seconds: Maximum duration of cooldown pause in seconds
            test_mode: If True, logs emails to file instead of sending
        """
        self.credentials_path = credentials_path
        self.resume_pdf_path = Path(resume_pdf_path)
        self.email_delay_min_seconds = email_delay_min_seconds
        self.email_delay_max_seconds = email_delay_max_seconds
        self.cooldown_every_n_emails = cooldown_every_n_emails
        self.cooldown_min_seconds = cooldown_min_seconds
        self.cooldown_max_seconds = cooldown_max_seconds
        self.test_mode = test_mode
        self.last_send_time = 0
        self._emails_sent_this_session = 0
        self.service = None
        self._init_service()


    def _init_service(self):
        """Initialize Gmail API service."""
        try:
            from google.auth.transport.requests import Request
            from google_auth_oauthlib.flow import InstalledAppFlow
            import pickle
            
            SCOPES = ["https://www.googleapis.com/auth/gmail.send"]
            
            creds = None
            
            # Store token in the same directory as credentials to ensure user-isolation
            # e.g., resume/Ramana/token.pickle instead of project root
            cred_path = Path(self.credentials_path).resolve()
            token_path = cred_path.parent / "token.pickle"
            
            # Check for saved token
            if token_path.exists():
                with open(token_path, "rb") as token_file:
                    creds = pickle.load(token_file)
            
            # If no valid credentials, get new ones
            if not creds or not creds.valid:
                if creds and creds.expired and creds.refresh_token:
                    creds.refresh(Request())
                else:
                    flow = InstalledAppFlow.from_client_secrets_file(
                        str(cred_path), SCOPES
                    )
                    creds = flow.run_local_server(port=0)
                
                # Save credentials for next time
                with open(token_path, "wb") as token_file:
                    pickle.dump(creds, token_file)
            
            from googleapiclient.discovery import build
            self.service = build("gmail", "v1", credentials=creds)
            logger.info(f"Gmail API service initialized successfully (Token: {token_path})")
            
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
        # Cooldown: every N emails, take a long break to avoid rate-limit detection
        if self._emails_sent_this_session > 0 and self._emails_sent_this_session % self.cooldown_every_n_emails == 0:
            cooldown_duration = random.uniform(self.cooldown_min_seconds, self.cooldown_max_seconds)
            logger.info(f"🕐 Cooldown triggered after {self._emails_sent_this_session} emails. "
                        f"Pausing for {cooldown_duration:.1f}s...")
            time.sleep(cooldown_duration)

        # Randomized jitter delay — makes send pattern look human, not robotic
        time_since_last = time.time() - self.last_send_time
        if self.last_send_time > 0:  # skip delay before very first email
            jitter = random.uniform(self.email_delay_min_seconds, self.email_delay_max_seconds)
            remaining = jitter - time_since_last
            if remaining > 0:
                logger.info(f"⏳ Waiting {remaining:.1f}s before next email (jitter: {jitter:.1f}s)...")
                time.sleep(remaining)

        self.last_send_time = time.time()
        self._emails_sent_this_session += 1

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
            logger.info(f"Email sent to {recipient_email}. Message ID: {message_id}")
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

        # Convert plain text body to simple HTML for natural text flow in Gmail
        paragraphs = body.split("\n\n")
        html_body = ""
        for para in paragraphs:
            # Preserve single line breaks within paragraphs
            para_html = para.strip().replace("\n", "<br>")
            if para_html:
                html_body += f"<p style=\"margin:0 0 1em 0;\">{para_html}</p>\n"
        
        html_content = f"""<div style="font-family:Arial,Helvetica,sans-serif;font-size:14px;color:#222;">
{html_body}</div>"""
        
        msg.attach(MIMEText(html_content, "html"))

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
            
            logger.info("✓ Gmail API service initialized with send scope")
            return True, "Gmail API ready to send emails"
            
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
        logger.info(f"[TEST MODE] Email logged: {recipient_email}")
        return True, message_id
