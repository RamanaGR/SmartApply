"""Email prompt builder."""

import json
import logging
from typing import Optional
from src.models.resume import ResumeData

logger = logging.getLogger(__name__)


class PromptBuilder:
    """Build email generation prompts for LLM."""
    
    def __init__(self, resume_data: ResumeData, user_name: str):
        """
        Initialize prompt builder.
        
        Args:
            resume_data: Candidate resume data
            user_name: Candidate name
        """
        self.resume_data = resume_data
        self.user_name = user_name
        self.companies_in_resume = self._extract_companies_from_resume()
    
    def _extract_social_networks(self) -> dict:
        """
        Extract LinkedIn and GitHub URLs from resume.
        
        Returns:
            Dict with 'linkedin_url' and 'github_url' if present
        """
        social_networks = {}
        try:
            raw_data = self.resume_data.raw_data or {}
            cv = raw_data.get("cv", {})
            networks = cv.get("social_networks", [])
            
            if isinstance(networks, list):
                for network in networks:
                    if isinstance(network, dict):
                        network_name = network.get("network", "").lower()
                        username = network.get("username", "")
                        
                        if network_name == "linkedin" and username:
                            social_networks["linkedin_url"] = f"https://linkedin.com/in/{username}"
                        elif network_name == "github" and username:
                            social_networks["github_url"] = f"https://github.com/{username}"
            
            if social_networks:
                logger.info(f"Extracted social networks: {list(social_networks.keys())}")
        except Exception as e:
            logger.warning(f"Could not extract social networks: {e}")
        
        return social_networks
    
    def _extract_company_experiences(self) -> dict:
        """
        Extract company experiences with specific technologies and responsibilities.
        
        Returns:
            Dict mapping company name to {position, highlights, years}
        """
        experiences = {}
        try:
            raw_data = self.resume_data.raw_data or {}
            cv = raw_data.get("cv", {})
            sections = cv.get("sections", {})
            experience = sections.get("experience", [])
            
            if isinstance(experience, list):
                for exp in experience:
                    if isinstance(exp, dict):
                        company = exp.get("company")
                        if company:
                            position = exp.get("position", "")
                            highlights = exp.get("highlights", [])
                            date_info = exp.get("date", {})
                            
                            experiences[company] = {
                                "position": position,
                                "highlights": highlights,
                                "start_date": date_info.get("start_date", ""),
                                "end_date": date_info.get("end_date")
                            }
            
            logger.info(f"Extracted {len(experiences)} company experiences from resume")
        except Exception as e:
            logger.warning(f"Could not extract company experiences: {e}")
        
        return experiences
    
    def _extract_companies_from_resume(self) -> list:
        """
        Extract company names from resume dynamically.
        
        Returns:
            List of company names from most recent to oldest
        """
        companies = []
        try:
            experiences = self._extract_company_experiences()
            companies = list(experiences.keys())
            logger.info(f"Extracted companies from resume (in order): {companies}")
        except Exception as e:
            logger.warning(f"Could not extract companies from resume: {e}")
        
        return companies
    
    def build_prompt(
        self,
        job_description: str,
        recruiter_name: Optional[str] = None,
        company_from_email: Optional[str] = None
    ) -> str:
        """
        Build bulletproof prompt for LLM email generation.
        
        Args:
            job_description: Job posting from CSV
            recruiter_name: Extracted recruiter name (optional)
            company_from_email: Company extracted from email domain (fallback)
            
        Returns:
            Complete prompt for LLM
        """
        # Build dynamic technology mapping from actual resume (only 2 highlights per company)
        company_experiences = self._extract_company_experiences()
        tech_mapping = ""
        if company_experiences:
            tech_mapping = "CANDIDATE'S ACTUAL SKILLS BY COMPANY (extracted from their real resume):\n"
            for company, details in company_experiences.items():
                tech_mapping += f"\n{company}:\n"
                tech_mapping += f"  Role: {details['position']}\n"
                tech_mapping += f"  Technologies and skills used:\n"
                for highlight in details['highlights'][:2]:  # Only 2 most relevant highlights
                    tech_mapping += f"    {highlight}\n"
        
        # Extract social network URLs
        social_networks = self._extract_social_networks()
        linkedin_url = social_networks.get("linkedin_url", "")
        github_url = social_networks.get("github_url", "")
        
        # Build social links section for email - MANDATORY if present
        social_links_for_email = ""
        if linkedin_url or github_url:
            social_links_for_email = "Social Media Links (MANDATORY - must include in email):\n"
            if linkedin_url:
                social_links_for_email += f"{linkedin_url}\n"
            if github_url:
                social_links_for_email += f"{github_url}\n"
        
        resume_str = json.dumps(self.resume_data.raw_data, indent=2) if self.resume_data.raw_data else "Resume data not available"
        greeting = f"Dear {recruiter_name}," if recruiter_name else "Dear Hiring Manager,"

        prompt = f"""You are an expert recruiter writing professional job application emails.

CRITICAL RULES - NO EXCEPTIONS:
1. ONLY use technologies EXPLICITLY stated in BOTH candidate resume AND job posting
2. NEVER assume, hallucinate, or infer any technology not explicitly written
3. NEVER modify candidate's experience - use exact words from resume
4. NEVER mention resume company names (Optum, Innovapath, Wipro, etc.)
5. ONLY mention company from job posting
6. NEVER use vague language - all tech names must be SPECIFIC
7. Match candidate to job based on SPECIFIC overlapping technologies
8. NEVER extract recruiter/contact names from the job description text - ONLY use the greeting provided below

JOB POSTING REQUIREMENTS:
{job_description}

MATCHING ALGORITHM:
- Extract specific technologies from job posting
- Search candidate resume for exact matches
- If exact match: Use candidate's specific experience with that technology
- If no exact match: Find closest related technology candidate has (e.g., Java vs Python)
- If no close match: Focus on transferable skills from strongest experience
- ALWAYS reference most recent/current role first

EMAIL REQUIREMENTS:
- Subject: Specific job title + company name (e.g., "Application for Data Scientist at Cruisedyno")
  Use fallback if not in posting: {company_from_email if company_from_email else 'job posting'}
  NEVER use placeholders

- Body: Maximum 120 words (paragraphs only, no lists)
  • Para 1: Role interest + specific tech from job posting
  • Para 2: Most recent role with actual technologies used
  • Para 3: Express genuine interest
  
- Resume statement: MUST include "I have attached my resume for your reference."

- Social links: WILL BE APPENDED AUTOMATICALLY by the system
  Do NOT include them in the email body yourself

- Signature: "Best regards, {self.user_name}"

- Formatting: Plain text only - no bullets, dashes, asterisks, or special characters

{tech_mapping}

RESPONSE FORMAT - CRITICAL:
You MUST write the email in this exact format:

SUBJECT: Application for [Job Title] at [Company Name]

BODY:
{greeting}

[Paragraph 1: Express interest in the role, mention 1-2 specific technologies from the job posting that you have experience with]

[Paragraph 2: Describe your most recent/current role and the specific technologies and projects you worked on. Use exact language from your resume highlights.]

[Paragraph 3: Express genuine interest in the opportunity and how your skills align with this role]

I have attached my resume for your reference.

Best regards,
{self.user_name}

EXAMPLE OUTPUT (do not copy, adapt for the actual job):
SUBJECT: Application for Data Scientist at Cruisedyno
BODY:
{greeting}

I'm excited about the Data Scientist role at Cruisedyno. With experience in Python and machine learning algorithms, I believe I can contribute effectively to your team.

In my current role at Optum, I've developed skills in building intelligent systems for document understanding using Google Document AI and Neo4j to extract key information from contracts.

I'm genuinely interested in this opportunity and would like to discuss how my experience can benefit your organization.

I have attached my resume for your reference.

Best regards,
{self.user_name}

FINAL CHECKLIST:
1. Subject: job title + actual company name (no placeholders)
2. Body: 3 plain text paragraphs only (no bullets/dashes/asterisks)
3. Technologies: Only from BOTH resume AND job posting
4. Resume statement: MUST include "I have attached my resume..."
5. No resume company names: NEVER mention (Optum, Innovapath, etc.)
6. Signature: Correct candidate name
7. Do NOT include social links - system will append them automatically
8. Greeting: You MUST use EXACTLY this greeting: {greeting} — do NOT change or substitute it with any name from the job description

NOW WRITE THE EMAIL:"""

        return prompt
