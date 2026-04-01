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
                            
                            end_date = date_info.get("end_date")
                            is_current = end_date is None or str(end_date).strip().lower() == "present"
                            
                            experiences[company] = {
                                "position": position,
                                "highlights": highlights,
                                "start_date": date_info.get("start_date", ""),
                                "end_date": end_date,
                                "is_current": is_current
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
        # Build dynamic technology mapping from actual resume (1 highlight per company to save tokens)
        company_experiences = self._extract_company_experiences()
        tech_mapping = ""
        if company_experiences:
            tech_mapping = "CANDIDATE EXPERIENCE OPTIONS:\n"
            for company, details in company_experiences.items():
                status = "CURRENT ROLE" if details.get("is_current") else "PAST ROLE"
                highlight = details['highlights'][0] if details['highlights'] else ""
                tech_mapping += f"- {company} [{status}]: {details['position']}. Key work: {highlight}\n"
        
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

        prompt = f"""You are a helpful assistant assisting a real candidate in drafting a factual, professional job application email based strictly on their actual resume experience.

IMPORTANT GUIDELINES:
1. BREVITY: Keep the entire email body under 75 words. Be direct and polite.
2. TRUTHFULNESS: Only mention skills and technologies perfectly aligned between the candidate's provided experience below and the job description. Never invent information.
3. ACCURACY: Honestly state the candidate's company history simply based on the specific CANDIDATE EXPERIENCE OPTIONS provided.
4. TARGET: Focus the application towards the hiring company ({company_from_email if company_from_email else 'job posting'}).
5. GREETING: Do not extract names, strictly use the provided greeting.

JOB POSTING:
{job_description}

{tech_mapping}

REQUIRED EMAIL FORMAT:
You MUST output strictly in the format below:

SUBJECT: Application for [Job Title] at [Company Name]

BODY:
{greeting}

[Para 1: Express interest in the role. Note 1 or 2 matching technologies from the job posting. (Max 2 short sentences)]

[Para 2: Summarize a factual experience related to those technologies. 
If the experience is from a [CURRENT ROLE] below, use: "In my current role at [EXACT COMPANY NAME]..." 
If it is from a [PAST ROLE] below, use: "During my time at [EXACT COMPANY NAME]..." 
(Max 2 short sentences)]

[Para 3: Express genuine interest in the opportunity. (1 brief sentence ONLY)]

I have attached my resume for your reference.

Regards,
{self.user_name}

FINAL CHECKLIST:
1. Subject: job title + actual company name (No placeholders)
2. Body: Strictly under 75 words total for the entire body
3. Technologies: Only use real skills mapped from the candidate experience above
4. Signature: Correct candidate name
5. MUST physically output the exact words "SUBJECT:" and "BODY:"!

NOW DRAFT THE EMAIL:"""

        return prompt

    def build_simple_prompt(
        self,
        job_description: str,
        recruiter_name: Optional[str] = None,
        company_from_email: Optional[str] = None
    ) -> str:
        """
        Build a shorter, simpler prompt for LLM retry attempt 2.
        Fewer instructions = less to confuse the model.
        """
        greeting = f"Dear {recruiter_name}," if recruiter_name else "Dear Hiring Manager,"
        company = company_from_email or "the company"

        # Get top 3 skills only
        skills = []
        if self.resume_data.skills:
            skills = self.resume_data.skills[:3]
        skills_str = ", ".join(skills) if skills else "software development"

        prompt = f"""Write a short professional job application email. Keep it under 80 words.

Recruiter greeting: {greeting}
Company: {company}
Candidate name: {self.user_name}
Candidate top skills: {skills_str}

Job posting:
{job_description[:600]}

You MUST output EXACTLY in this format:
SUBJECT: <subject line here>
BODY:
{greeting}

<2-3 sentence email body here>

I have attached my resume for your reference.

Regards,
{self.user_name}

WRITE THE EMAIL NOW:"""

        return prompt

    def build_minimal_prompt(
        self,
        job_description: str,
        company_from_email: Optional[str] = None
    ) -> str:
        """
        Build a bare-bones prompt for LLM retry attempt 3.
        Absolute minimum — hardest to fail structurally.
        """
        company = company_from_email or "the company"
        name = self.user_name

        prompt = f"""Write a 3-sentence job application email from {name} to {company}.

Job: {job_description[:300]}

Output format (use exactly these labels):
SUBJECT: Application from {name}
BODY:
Dear Hiring Manager,

<3 sentences expressing interest and skills>

Regards,
{name}"""

        return prompt
