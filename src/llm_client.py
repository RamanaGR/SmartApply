"""
LLM Client module for SmartApply.
Handles communication with local Ollama LLM, resume loading, prompt building, and response parsing.
"""

import json
import logging
import time
import requests
from pathlib import Path
from typing import Dict, Any, Optional, Tuple

logger = logging.getLogger(__name__)


class OllamaClient:
    """Client for communicating with local Ollama LLM."""

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "llama3",
        timeout_seconds: int = 30,
        max_retries: int = 3,
        retry_backoff_multiplier: float = 2.0
    ):
        """
        Initialize Ollama client.
        
        Args:
            base_url: Ollama API base URL
            model: Model name to use
            timeout_seconds: Request timeout in seconds
            max_retries: Number of retry attempts on failure
            retry_backoff_multiplier: Backoff multiplier for retries (2.0 = 2s, 4s, 8s)
        """
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.retry_backoff_multiplier = retry_backoff_multiplier

    def generate(self, prompt: str) -> Tuple[bool, str]:
        """
        Generate text from prompt with retry logic.
        
        Args:
            prompt: Input prompt for the model
            
        Returns:
            Tuple of (success: bool, response: str)
        """
        for attempt in range(self.max_retries):
            try:
                backoff_delay = (2 ** attempt) if attempt > 0 else 0
                if backoff_delay > 0:
                    logger.warning(f"Retry attempt {attempt + 1}/{self.max_retries} after {backoff_delay}s delay")
                    time.sleep(backoff_delay)

                response = requests.post(
                    f"{self.base_url}/api/generate",
                    json={
                        "model": self.model,
                        "prompt": prompt,
                        "stream": False,
                    },
                    timeout=self.timeout_seconds
                )

                if response.status_code == 200:
                    data = response.json()
                    generated_text = data.get("response", "").strip()
                    logger.debug(f"Generated text length: {len(generated_text)} chars")
                    return True, generated_text

                elif response.status_code == 404:
                    error_msg = f"Model '{self.model}' not found on Ollama. Available models: {self._get_available_models()}"
                    logger.error(error_msg)
                    return False, error_msg

                else:
                    error_msg = f"Ollama API error: {response.status_code} - {response.text}"
                    logger.warning(f"Attempt {attempt + 1}/{self.max_retries}: {error_msg}")

            except requests.exceptions.Timeout:
                error_msg = f"Ollama request timeout ({self.timeout_seconds}s)"
                logger.warning(f"Attempt {attempt + 1}/{self.max_retries}: {error_msg}")

            except requests.exceptions.ConnectionError as e:
                error_msg = f"Cannot connect to Ollama at {self.base_url}: {e}"
                logger.warning(f"Attempt {attempt + 1}/{self.max_retries}: {error_msg}")

            except Exception as e:
                error_msg = f"Unexpected error: {e}"
                logger.warning(f"Attempt {attempt + 1}/{self.max_retries}: {error_msg}")

        return False, f"Failed to generate response after {self.max_retries} attempts"

    def _get_available_models(self) -> str:
        """Get list of available models from Ollama."""
        try:
            response = requests.get(f"{self.base_url}/api/tags", timeout=5)
            if response.status_code == 200:
                models = [m["name"] for m in response.json().get("models", [])]
                return ", ".join(models) if models else "None"
        except Exception as e:
            logger.debug(f"Could not fetch available models: {e}")
        return "Unable to fetch"

    def is_available(self) -> bool:
        """Check if Ollama is available and responsive."""
        try:
            response = requests.get(f"{self.base_url}/api/tags", timeout=5)
            return response.status_code == 200
        except Exception as e:
            logger.debug(f"Ollama connectivity check failed: {e}")
            return False


class EmailGenerator:
    """Generate personalized emails using LLM based on resume and job description."""

    GENERIC_EMAIL_TEMPLATE = """
Subject: Application for {job_title}

Dear Hiring Manager,

I am writing to express my interest in the {job_title} position at your organization.

With my background in {skills_preview}, I am confident that I can contribute effectively to your team. I have experience in key areas relevant to this role and am excited about the opportunity to apply my skills in a dynamic environment.

I have attached my resume for your review. I would welcome the opportunity to discuss how my qualifications align with your needs.

Thank you for considering my application. I look forward to hearing from you.

Best regards,
[Your Name]
"""

    def __init__(self, resume_json_path: str, ollama_client: Optional[OllamaClient] = None):
        """
        Initialize EmailGenerator.
        
        Args:
            resume_json_path: Path to resume.json file
            ollama_client: Optional OllamaClient instance. If None, uses defaults.
        """
        self.resume_json_path = Path(resume_json_path)
        self.ollama_client = ollama_client or OllamaClient()
        self.resume_data = self._load_resume()
        self.user_name = self._get_user_name()

    def _load_resume(self) -> Dict[str, Any]:
        """Load and parse resume.json."""
        if not self.resume_json_path.exists():
            logger.warning(f"Resume file not found: {self.resume_json_path}")
            return {}

        try:
            with open(self.resume_json_path, "r") as f:
                data = json.load(f)
                logger.info(f"Loaded resume: {self.resume_json_path}")
                return data
        except Exception as e:
            logger.error(f"Failed to load resume: {e}")
            return {}

    def _get_user_name(self) -> str:
        """Extract user name from resume data."""
        try:
            name = self.resume_data.get("cv", {}).get("name", "")
            if name:
                logger.info(f"User name from resume: {name}")
                return name
        except Exception as e:
            logger.error(f"Failed to extract name from resume: {e}")
        return "Applicant"

    def generate_email(self, job_description: str, use_llm: bool = True, skip_llm_on_error: bool = True) -> Dict[str, str]:
        """
        Generate personalized email for a job posting.
        
        Args:
            job_description: Job description from CSV
            use_llm: Whether to use LLM (False = use template)
            skip_llm_on_error: Fall back to template if LLM fails
            
        Returns:
            Dict with "subject" and "body" keys
        """
        if not use_llm:
            return self._get_template_email(job_description)

        # Build prompt
        prompt = self._build_prompt(job_description)

        # Generate using LLM
        success, response = self.ollama_client.generate(prompt)

        if not success:
            logger.error(f"LLM generation failed: {response}")
            if skip_llm_on_error:
                logger.info("Falling back to template email")
                return self._get_template_email(job_description)
            else:
                return {"subject": "ERROR", "body": f"Failed to generate email: {response}"}

        # Parse LLM response
        email = self._parse_llm_response(response)
        if email and email.get("subject") and email.get("body"):
            return email
        else:
            logger.warning("Failed to parse LLM response. Falling back to template.")
            if skip_llm_on_error:
                return self._get_template_email(job_description)
            else:
                return {"subject": "ERROR", "body": "Failed to parse LLM response"}

    def _build_prompt(self, job_description: str) -> str:
        """Build prompt for LLM combining resume and job description."""
        resume_str = json.dumps(self.resume_data, indent=2) if self.resume_data else "Resume data not available"

        prompt = f"""You are an expert recruiter writing concise job application emails. Write SHORT, CRISP emails (max 150 words).

CANDIDATE PROFILE:
{resume_str}

JOB POSTING:
{job_description}

INSTRUCTIONS:
1. Identify the specific job title/role from the job posting
2. Write a SHORT, CRISP email - max 150 words total
3. Match candidate's skills to job requirements in 1-2 lines
4. Reference 1-2 specific technologies/projects from resume that match the job
5. Show genuine interest in THIS specific role
6. Use candidate name: {self.user_name}
7. NO fluff, NO generic content - only relevant, specific details
8. Keep it professional but conversational

FORMAT:
SUBJECT: [Specific subject - example: "Application for Senior AI Engineer"]
BODY:
Dear Hiring Manager,

[2-3 short sentences matching your skills to the job]

[1-2 sentences with specific tech/experience]

[1 sentence expressing interest]

Best regards,
{self.user_name}

Write the CRISP email now (KEEP IT SHORT AND SPECIFIC):"""

        return prompt

    def _parse_llm_response(self, response: str) -> Optional[Dict[str, str]]:
        """Parse LLM response to extract subject and body."""
        try:
            # Look for SUBJECT: and BODY: markers
            subject_marker = "SUBJECT:"
            body_marker = "BODY:"

            subject_idx = response.find(subject_marker)
            body_idx = response.find(body_marker)

            if subject_idx == -1 or body_idx == -1:
                logger.warning("Could not find SUBJECT or BODY markers in LLM response")
                return None

            # Extract subject (between SUBJECT: and BODY:)
            subject = response[subject_idx + len(subject_marker):body_idx].strip()

            # Extract body (everything after BODY:)
            body = response[body_idx + len(body_marker):].strip()

            if not subject or not body:
                logger.warning("Subject or body is empty after parsing")
                return None

            return {"subject": subject, "body": body}

        except Exception as e:
            logger.error(f"Error parsing LLM response: {e}")
            return None

    def _get_template_email(self, job_description: str) -> Dict[str, str]:
        """Generate email using fallback template."""
        # Extract job title from description if possible
        job_title = self._extract_job_title(job_description)
        skills = self._get_skills_preview()

        body = self.GENERIC_EMAIL_TEMPLATE.format(
            job_title=job_title,
            skills_preview=skills
        )

        subject = f"Application for {job_title} Position"

        return {"subject": subject, "body": body}

    def _extract_job_title(self, job_description: str) -> str:
        """Extract job title from description."""
        lines = job_description.split("\n")
        for line in lines[:5]:  # Check first 5 lines
            if "title" in line.lower() or "position" in line.lower():
                return line.replace("title", "").replace("position", "").replace(":", "").strip()[:50]
        return "Software Engineer"  # Default fallback

    def _get_skills_preview(self) -> str:
        """Get skills preview from resume."""
        if not self.resume_data:
            return "various technical and professional areas"

        skills = self.resume_data.get("skills", [])
        if isinstance(skills, list) and skills:
            return ", ".join(skills[:3])
        return "various technical and professional areas"
