"""Email validator service."""

import re
import logging
from typing import Tuple, List
from src.models.email import EmailValidationResult

logger = logging.getLogger(__name__)


class EmailValidatorService:
    """Validate email content for quality issues."""
    
    PLACEHOLDER_PATTERNS = [
        r'\[company name\]',
        r'\[your name\]',
        r'\[hiring manager\]',
        r'\[position\]',
        r'\[company\]',
        r'\[name\]'
    ]

    GENERIC_SUBJECT_PATTERNS = [
        r'application for it staffing',
        r'application for consultants',
        r'application for resources',
        r'application for this opportunity',
        r'application for opportunity',
        r'^application for [a-z\s]+$(?! at )',  # Too generic if no "at CompanyName" following it
    ]

    VAGUE_PHRASES = [
        'this opportunity',
        'available resources',
        'c2c positions',
        'above technologies',
        'mentioned technologies',
        'relevant positions'
    ]
    
    @staticmethod
    def validate(subject: str, body: str) -> EmailValidationResult:
        """
        Validate email content.
        
        Args:
            subject: Email subject
            body: Email body
            
        Returns:
            EmailValidationResult with errors and warnings
        """
        errors = []
        warnings = []
        
        subject = subject.strip() if subject else ""
        body = body.strip() if body else ""
        
        # Check for missing fields
        if not subject:
            errors.append("Subject is empty")
        if not body:
            errors.append("Body is empty")
        
        # Check for placeholder text
        for pattern in EmailValidatorService.PLACEHOLDER_PATTERNS:
            if subject and re.search(pattern, subject, re.IGNORECASE):
                errors.append(f"Subject contains placeholder: {pattern}")
            if body and re.search(pattern, body, re.IGNORECASE):
                errors.append(f"Body contains placeholder: {pattern}")
        
        # Check for generic/vague subject lines
        if subject:
            for pattern in EmailValidatorService.GENERIC_SUBJECT_PATTERNS:
                if re.search(pattern, subject, re.IGNORECASE):
                    # Allow if it has "at CompanyName" (e.g., "Application for Data Scientist at Cruisedyno")
                    if ' at ' in subject.lower():
                        break  # Has company name, so it's not too generic
                    errors.append(f"Subject too generic: '{subject}' - should mention specific role/company")
                    break
            
            # Check for vague phrases
            subject_lower = subject.lower()
            for phrase in EmailValidatorService.VAGUE_PHRASES:
                if phrase in subject_lower:
                    errors.append(f"Subject contains vague phrase: '{phrase}' - be more specific")
                    break
        
        # Check for quality issues
        if subject and len(subject) < 5:
            errors.append("Subject too short (< 5 chars)")
        if subject and len(subject) > 150:
            warnings.append("Subject quite long (> 150 chars)")
        
        if body and len(body) < 50:
            errors.append("Body too short (< 50 chars)")
        if body and len(body) > 500:
            warnings.append("Body quite long (> 500 chars)")
        
        # Check for "Dear Hiring Manager" - indicates generic email
        if body and "dear hiring manager" in body.lower():
            warnings.append("Using generic 'Dear Hiring Manager' - consider personalizing")
        
        # Check for common issues
        if body and "[your name]" in body.lower():
            errors.append("Contains '[Your Name]' instead of actual name")
        
        # Check for vague phrases in body
        if body:
            body_lower = body.lower()
            if 'this opportunity' in body_lower:
                warnings.append("Body uses vague 'this opportunity' - mention specific role/company")
            if 'above technologies' in body_lower or 'mentioned technologies' in body_lower:
                warnings.append("Body references vague tech terms - name specific technologies")
        
        is_valid = len(errors) == 0
        return EmailValidationResult(is_valid=is_valid, errors=errors, warnings=warnings)
