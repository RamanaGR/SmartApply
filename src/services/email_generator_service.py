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
    
    GENERIC_EMAIL_TEMPLATE = """Subject: Application for {job_title} Position

Dear Hiring Manager,

I am writing to express my interest in the {job_title} position at your organization.

With my background in {skills_preview}, I am confident that I can contribute effectively to your team. I have experience in key areas relevant to this role and am excited about the opportunity to apply my skills in a dynamic environment.

I have attached my resume for your review. I would welcome the opportunity to discuss how my qualifications align with your needs.

Thank you for considering my application. I look forward to hearing from you.

Best regards,
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
        contact_info: Optional[str] = None
    ) -> Email:
        """
        Generate email for job posting.
        
        Args:
            job_description: Job posting description
            recipient_email: Email recipient
            use_llm: Whether to use LLM (False = use template)
            skip_llm_on_error: Fall back to template if LLM fails
            company_from_csv: Company name from CSV (takes precedence)
            contact_info: Contact info from CSV (contains recruiter email)
            
        Returns:
            Email object
        """
        if not use_llm:
            return self._generate_template_email(job_description, recipient_email)
        
        # Extract recruiter name strictly from contact info email
        recruiter_name = self._extract_recruiter_name(contact_info)
        
        # Use company from CSV if available, otherwise try email domain
        if company_from_csv:
            company_to_use = company_from_csv
            logger.info(f"Using company from CSV: {company_to_use}")
        else:
            company_to_use = self._extract_company_from_email(recipient_email)
        
        # Build prompt
        prompt = self.prompt_builder.build_prompt(job_description, recruiter_name, company_to_use)
        
        # Generate using LLM
        success, response = self.ollama_service.generate(prompt)
        
        if not success:
            logger.error(f"LLM generation failed: {response}")
            if skip_llm_on_error:
                logger.info("Falling back to template email")
                return self._generate_template_email(job_description, recipient_email)
            else:
                return Email(recipient_email, "ERROR", f"Failed to generate: {response}")
        
        # Parse LLM response
        email = self._parse_llm_response(response, recipient_email)
        if email:
            return email
        
        logger.warning("Failed to parse LLM response. Falling back to template.")
        if skip_llm_on_error:
            return self._generate_template_email(job_description, recipient_email)
        else:
            return Email(recipient_email, "ERROR", "Failed to parse LLM response")
    
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
        try:
            if '@' not in email:
                return None
            domain = email.split('@')[1].split('.')[0]  # Get domain without TLD
            if domain:
                # Capitalize first letter for better formatting
                company_name = domain.capitalize()
                logger.info(f"Extracted company from email domain: {company_name}")
                return company_name
        except Exception as e:
            logger.warning(f"Could not extract company from email: {e}")
        return None
    
    def _parse_llm_response(self, response: str, recipient_email: str) -> Optional[Email]:
        """Parse LLM response to extract subject and body, then append social links."""
        try:
            subject_marker = "SUBJECT:"
            body_marker = "BODY:"
            
            subject_idx = response.find(subject_marker)
            body_idx = response.find(body_marker)
            
            if subject_idx == -1 or body_idx == -1:
                logger.warning("Could not find SUBJECT or BODY markers")
                return None
            
            subject = response[subject_idx + len(subject_marker):body_idx].strip()
            body = response[body_idx + len(body_marker):].strip()
            
            if not subject or not body:
                logger.warning("Subject or body is empty")
                return None
            
            # Remove any social links the LLM might have added (we'll add them programmatically)
            body = self._remove_llm_social_links(body)
            
            # Append social links from resume with proper formatting
            body = self._append_social_links(body)
            
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
    
    def _append_social_links(self, body: str) -> str:
        """Append social links before signature with proper formatting."""
        social_networks = self.prompt_builder._extract_social_networks()
        
        if not social_networks:
            return body
        
        # Find the "Best regards" signature line
        signature_marker = "Best regards,"
        signature_idx = body.find(signature_marker)
        
        # Build social links text
        social_links_text = ""
        if social_networks.get("linkedin_url"):
            social_links_text += f"LinkedIn: {social_networks['linkedin_url']}\n"
        if social_networks.get("github_url"):
            social_links_text += f"GitHub: {social_networks['github_url']}\n"
        
        if not social_links_text:
            return body
        
        # Insert URLs before the signature
        if signature_idx != -1:
            # Insert before "Best regards" with proper spacing
            before_signature = body[:signature_idx].rstrip()
            after_signature = body[signature_idx:]
            body = before_signature + "\n\n" + social_links_text + "\n" + after_signature
        else:
            # If no signature found, append at end
            body = body.rstrip() + "\n\n" + social_links_text
        
        return body
    
    def _generate_template_email(self, job_description: str, recipient_email: str) -> Email:
        """Generate email using fallback template."""
        job_title = self._extract_job_title(job_description)
        skills = self._get_skills_preview()
        
        body = self.GENERIC_EMAIL_TEMPLATE.format(
            job_title=job_title,
            skills_preview=skills,
            candidate_name=self.user_name
        )
        
        subject = f"Application for {job_title} at {self._extract_company_from_email(recipient_email) or 'Company'}"
        return Email(recipient_email, subject, body)
    
    def _extract_job_title(self, job_description: str) -> str:
        """Extract job title from description."""
        lines = job_description.split("\n")
        for line in lines[:5]:
            if "title" in line.lower() or "position" in line.lower():
                return line.replace("title", "").replace("position", "").replace(":", "").strip()[:50]
        return "Software Engineer"
    
    def _get_skills_preview(self) -> str:
        """Get skills preview from resume."""
        if self.resume_data.skills:
            return ", ".join(self.resume_data.skills[:3])
        return "various technical and professional areas"
