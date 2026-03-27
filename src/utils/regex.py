"""Regex patterns used throughout SmartApply."""

import re
from typing import List, Optional


class EmailRegex:
    """Email pattern definitions and utilities."""
    
    # Match standard email format
    PATTERN = r'^[^\s@]+@[^\s@]+\.[^\s@]+$'
    
    # Find emails in text
    FIND_PATTERN = r'[\w\.-]+@[\w\.-]+\.\w+'
    
    # Extract from "Email: xxx@xxx.com" format
    EMAIL_PREFIX_PATTERN = r'Email:\s*([^\s,]+)'
    
    @staticmethod
    def is_valid(email: str) -> bool:
        """Check if string is valid email."""
        return bool(re.match(EmailRegex.PATTERN, email))
    
    @staticmethod
    def find_all(text: str) -> List[str]:
        """Find all email addresses in text."""
        return re.findall(EmailRegex.FIND_PATTERN, text)
    
    @staticmethod
    def extract_from_prefixed_format(text: str) -> Optional[str]:
        """Extract email from 'Email: xxx' format."""
        match = re.search(EmailRegex.EMAIL_PREFIX_PATTERN, text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
        return None


class NameRegex:
    """Name extraction and formatting utilities."""
    
    # Remove separators and extract words
    SEPARATOR_PATTERN = r'[._-]'
    
    # Filter non-alphabetic characters
    WORD_PATTERN = r'\w+'
    
    @staticmethod
    def extract_name_from_email_username(email_username: str) -> str:
        """
        Extract and format name from email username.
        Example: john.doe123 -> John Doe
        """
        # Remove separators
        name = re.sub(NameRegex.SEPARATOR_PATTERN, ' ', email_username)
        # Keep only alphabetic words
        words = [word.capitalize() for word in name.split() if word.isalpha()]
        return ' '.join(words)
