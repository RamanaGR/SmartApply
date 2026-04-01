"""Email generation service using LLM."""

import logging
import re
from typing import Optional
from src.models.email import Email
from src.models.resume import ResumeData
from src.services.ollama_service import OllamaService
from src.services.prompt_builder import PromptBuilder
from src.utils.regex import EmailRegex, NameRegex

logger = logging.getLogger(__name__)


class EmailGeneratorService:
    """Generate personalized emails using LLM."""
    
    GENERIC_EMAIL_TEMPLATE = """{greeting}

I'm writing to express interest in the {job_title} role at {company_display}. With my background in {skills_preview}, I am confident I can contribute effectively to your team.

I have attached my resume for your review and welcome the opportunity to discuss my qualifications.

Regards,
{candidate_name}
"""
    
    def __init__(self, resume_data: ResumeData, user_name: str, ollama_service: Optional[OllamaService] = None):
        """
        Initialize email generator.
        
        Args:
            resume_data: Resume data for personalization
            user_name: Candidate name
            ollama_service: Ollama service instance
        """
        self.resume_data = resume_data
        self.user_name = user_name
        self.ollama_service = ollama_service or OllamaService()
        self.prompt_builder = PromptBuilder(resume_data, user_name)
    
    def generate(
        self,
        job_description: str,
        recipient_email: str,
        use_llm: bool = True,
        skip_llm_on_error: bool = True,
        company_from_csv: Optional[str] = None,
        contact_info: Optional[str] = None,
        job_title: Optional[str] = None,
        timeout_seconds: int = 40,
        retry_timeout_seconds: int = 12,
        minimal_timeout_seconds: int = 8,
        max_quality_retries: int = 3,
    ) -> Email:
        """
        Generate email for job posting with quality-based retry escalation.

        Args:
            job_description: Job posting description
            recipient_email: Email recipient
            use_llm: Whether to use LLM (False = use template)
            skip_llm_on_error: Fall back to template if all LLM attempts fail
            company_from_csv: Company name from CSV (takes precedence)
            contact_info: Contact info from CSV (contains recruiter email)
            job_title: Explicit job title from CSV
            timeout_seconds: Timeout budget for attempt 1 (detailed prompt)
            retry_timeout_seconds: Timeout budget for attempt 2 (simple prompt)
            minimal_timeout_seconds: Timeout budget for attempt 3 (minimal prompt)
            max_quality_retries: Max number of prompt escalation attempts

        Returns:
            Email object
        """
        # Extract recruiter name strictly from contact info email
        recruiter_name = self._extract_recruiter_name(contact_info)

        if not use_llm:
            return self._generate_template_email(job_description, recipient_email, recruiter_name, job_title)

        # Use company from CSV if available, otherwise try email domain
        if company_from_csv:
            company_to_use = company_from_csv
            logger.info(f"Using company from CSV: {company_to_use}")
        else:
            company_to_use = self._extract_company_from_email(recipient_email)

        # 3-level prompt escalation: detailed → simple → minimal
        attempts = [
            {
                "label": "detailed",
                "prompt": self.prompt_builder.build_prompt(job_description, recruiter_name, company_to_use),
                "timeout": timeout_seconds,
            },
            {
                "label": "simple",
                "prompt": self.prompt_builder.build_simple_prompt(job_description, recruiter_name, company_to_use),
                "timeout": retry_timeout_seconds,
            },
            {
                "label": "minimal",
                "prompt": self.prompt_builder.build_minimal_prompt(job_description, company_to_use),
                "timeout": minimal_timeout_seconds,
            },
        ]

        for attempt_num, attempt in enumerate(attempts[:max_quality_retries], start=1):
            logger.info(f"  → LLM attempt {attempt_num}/{max_quality_retries} [{attempt['label']} prompt, timeout={attempt['timeout']}s]")

            success, response = self.ollama_service.generate(
                attempt["prompt"],
                timeout_override=attempt["timeout"]
            )

            if not success:
                logger.warning(f"  → LLM attempt {attempt_num}: API/network failure — {response}")
                continue

            email = self._parse_llm_response(response, recipient_email, recruiter_name)
            if not email:
                logger.warning(f"  → LLM attempt {attempt_num}: Could not parse SUBJECT/BODY from response")
                continue

            passed, reason = self._check_quality(email, recruiter_name)
            if passed:
                logger.info(f"  ✓ LLM quality check passed on attempt {attempt_num} [{attempt['label']}]")
                return email
            else:
                logger.warning(f"  → LLM attempt {attempt_num} quality check FAILED: {reason}. Escalating...")

        # All attempts exhausted — fall back to template
        logger.warning(f"  ✗ All {max_quality_retries} LLM attempts failed quality check. Using template fallback.")
        if skip_llm_on_error:
            return self._generate_template_email(job_description, recipient_email, recruiter_name, job_title)
        else:
            return Email(recipient_email, "ERROR", "Failed to generate acceptable LLM email")

    def _check_quality(self, email: "Email", recruiter_name: Optional[str]) -> tuple:
        """
        Check if generated email meets quality standards.

        Returns:
            Tuple of (passed: bool, failure_reason: str)
        """
        subject = (email.subject or "").strip()
        body = (email.body or "").strip()

        if not subject or not body:
            return False, "empty_subject_or_body"

        word_count = len(body.split())
        if word_count < 30:
            return False, f"too_short ({word_count} words)"

        placeholders = ["[name]", "[company]", "[your name]", "[position]", "[role]", "[hiring manager]", "[job title]"]
        body_lower = body.lower()
        for p in placeholders:
            if p in body_lower:
                return False, f"placeholder_text_detected: '{p}'"

        if recruiter_name and "dear hiring manager" in body_lower:
            return False, "generic_greeting_when_recruiter_name_is_known"

        return True, "ok"


    
    def _extract_recruiter_name(self, contact_info: Optional[str]) -> Optional[str]:
        """Extract recruiter name strictly from contact info email."""
        if not contact_info:
            return None
        
        # Contact info format: "Email: xxx@example.com, Phone: yyy"
        # Extract email from contact info
        emails = EmailRegex.find_all(contact_info)
        
        if emails:
            email = emails[0]
            username = email.split('@')[0].lower()
            
            # Handle common email formats: john.doe, john_doe, johndoe, etc.
            # Replace separators with space for parsing
            name_parts = username.replace('.', ' ').replace('_', ' ').replace('-', ' ').split()
            
            if name_parts:
                # Capitalize each part properly
                capitalized_parts = [part.capitalize() for part in name_parts if part]
                
                if len(capitalized_parts) >= 2:
                    # Has first and last name
                    name = ' '.join(capitalized_parts[:2])
                    logger.info(f"Extracted recruiter name from contact info (first + last): {name}")
                    return name
                elif len(capitalized_parts) == 1:
                    # Only first name
                    name = capitalized_parts[0]
                    logger.info(f"Extracted recruiter name from contact info (first only): {name}")
                    return name
        
        return None
    
    def _extract_company_from_email(self, email: str) -> Optional[str]:
        """Extract company name from email domain (e.g., cruisedyno from srujana@cruisedyno.com)."""
        generic_domains = {"gmail", "yahoo", "hotmail", "outlook", "icloud", "aol", "mail"}
        try:
            if '@' not in email:
                return None
            domain = email.split('@')[1].split('.')[0].lower()  # Get domain without TLD
            if domain and domain not in generic_domains:
                # Capitalize first letter for better formatting
                company_name = domain.capitalize()
                logger.info(f"Extracted company from email domain: {company_name}")
                return company_name
            else:
                logger.info(f"Ignored generic email domain: {domain}")
        except Exception as e:
            logger.warning(f"Could not extract company from email: {e}")
        return None
    
    def _parse_llm_response(self, response: str, recipient_email: str, recruiter_name: Optional[str] = None) -> Optional[Email]:
        """Parse LLM response to extract subject and body, then append social links."""
        try:
            # Use regex to find markers case-insensitively and handle markdown bold (**SUBJECT:**)
            subject_match = re.search(r'\*?\*?SUBJECT\*?\*?\s*:', response, re.IGNORECASE)
            body_match = re.search(r'\*?\*?BODY\*?\*?\s*:', response, re.IGNORECASE)
            
            if not subject_match or not body_match:
                logger.warning("Could not find SUBJECT or BODY markers")
                logger.info(f"LLM response snippet: {response[:200]}...")
                return None
            
            # Subject spans from end of subject marker to start of body marker
            subject = response[subject_match.end():body_match.start()].strip()
            body = response[body_match.end():].strip()
            
            if not subject or not body:
                logger.warning("Subject or body is empty")
                return None
            
            # Enforce the correct greeting programmatically
            greeting_line = f"Dear {recruiter_name}," if recruiter_name else "Dear Hiring Manager,"
            lines = body.strip().split("\n")
            if lines and lines[0].strip().startswith(("Dear", "Hi ", "Hello ")):
                lines[0] = greeting_line
            elif lines:
                lines.insert(0, "")
                lines.insert(0, greeting_line)
            body = "\n".join(lines)
            
            # Remove any social links the LLM might have added (we'll add them programmatically)
            body = self._remove_llm_social_links(body)
            
            # Append social links programmatically so template remains clean
            body = self._append_footer(body)
            
            return Email(recipient_email, subject, body)
        
        except Exception as e:
            logger.error(f"Error parsing LLM response: {e}")
            return None
    
    def _remove_llm_social_links(self, body: str) -> str:
        """Remove any social links the LLM might have included."""
        lines = body.split("\n")
        filtered_lines = []
        
        for line in lines:
            # Skip lines that are just URLs or have LinkedIn/GitHub URLs
            stripped = line.strip()
            if stripped.startswith("http://") or stripped.startswith("https://"):
                continue
            if "linkedin.com" in stripped.lower() or "github.com" in stripped.lower():
                continue
            filtered_lines.append(line)
        
        return "\n".join(filtered_lines).strip()
    
    def _append_footer(self, body: str) -> str:
        """Append sign-off text and social links before signature."""
        
        # Determine if sign-off sentence is already in the body to avoid duplication
        footer_sentence = "I look forward to hearing from you."
        footer_text = ""
        if footer_sentence.lower() not in body.lower():
            footer_text += footer_sentence + "\n\n"
            
        social_networks = self.prompt_builder._extract_social_networks()
        if social_networks:
            if social_networks.get("linkedin_url"):
                footer_text += f"LinkedIn: {social_networks['linkedin_url']}\n"
            if social_networks.get("github_url"):
                footer_text += f"GitHub: {social_networks['github_url']}\n"
        
        if not footer_text.strip():
            return body
            
        # Find the "Regards," signature line
        signature_marker = "Regards,"
        signature_idx = body.find(signature_marker)
        
        # Insert URLs before the signature
        if signature_idx != -1:
            # Insert before "Regards" with proper spacing
            before_signature = body[:signature_idx].rstrip()
            after_signature = body[signature_idx:]
            body = before_signature + "\n\n" + footer_text.strip() + "\n\n" + after_signature
        else:
            # If no signature found, append at end
            body = body.rstrip() + "\n\n" + footer_text.strip()
        
        return body
    
    def _generate_template_email(self, job_description: str, recipient_email: str, recruiter_name: Optional[str] = None, explicit_job_title: Optional[str] = None) -> Email:
        """Generate email using fallback template."""
        job_title = explicit_job_title if explicit_job_title else self._extract_job_title(job_description)
        skills = self._get_skills_preview()
        company_name = self._extract_company_from_email(recipient_email)
        company_display = company_name if company_name else "your organization"
        greeting = f"Dear {recruiter_name}," if recruiter_name else "Dear Hiring Manager,"
        
        body = self.GENERIC_EMAIL_TEMPLATE.format(
            greeting=greeting,
            job_title=job_title,
            company_display=company_display,
            skills_preview=skills,
            candidate_name=self.user_name
        )
        subject = f"Application for {job_title} at {company_display}"
        
        body = self._append_footer(body)
        
        return Email(recipient_email, subject, body)
    
    def _extract_job_title(self, job_description: str) -> str:
        """Extract job title from description."""
        import re
        
        # Look for explicit definitions like 'Role Name: AI Engineer'
        match = re.search(r'(?i)(?:role|title|position)(?:\s+name)?\s*:\s*(.*?)(?=\s+(?:Location|Rate|Duration|Experience)|$)', job_description)
        if match:
            extracted = match.group(1).split('-')[0].split('(')[0].strip()
            if extracted and 3 < len(extracted) < 50:
                return extracted
                
        # Fallback to scanning first few lines
        lines = job_description.split("\n")
        bad_words = {"c2c", "w2", "h1b", "gc", "opt", "remote", "onsite", "hybrid", "hiring", "urgent", "requirement", "contract"}
        for line in lines[:5]:
            clean_line = line.strip()
            if clean_line and 5 < len(clean_line) < 50:
                words = set(clean_line.lower().replace('/', ' ').split())
                if not bad_words.intersection(words):
                    return clean_line
                    
        return "Software Engineer"
    
    def _get_skills_preview(self) -> str:
        """Get skills preview from resume."""
        if self.resume_data.skills:
            return ", ".join(self.resume_data.skills[:3])
        return "various technical and professional areas"
