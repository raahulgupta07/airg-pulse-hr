"""CV Extractor — LLM-powered structured extraction from CV text."""
from __future__ import annotations

import json
import re
import logging

import os
from backend.core.config import llm_call, CHAT_MODEL, LITE_MODEL

# STRUCTURE extraction model — defaults to LITE_MODEL (3-4x faster than CHAT_MODEL,
# JSON quality is comparable for structured extraction). Override via STRUCTURE_MODEL env.
STRUCTURE_MODEL = os.getenv("STRUCTURE_MODEL", LITE_MODEL)

logger = logging.getLogger(__name__)


def extract_structured_data(raw_text: str) -> dict:
    """Extract structured candidate data from raw CV text using LLM."""
    if not raw_text or len(raw_text) < 50:
        return _empty_result()

    prompt = f"""Extract structured data from this CV/resume. Return ONLY valid JSON.

CV TEXT:
{raw_text[:6000]}

Return this exact JSON structure:
{{
    "name": "Full Name",
    "email": "email@example.com or null",
    "phone": "+1234567890 or null",
    "location": "City, Country or null",
    "linkedin_url": "url or null",
    "current_role": "Exact job title of MOST RECENT role (e.g. 'HSE Manager', 'Senior Software Engineer'). Must be a real job title copied verbatim from the work-experience section. Never a hiring-decision word like 'hire'. Use null if unknown.",
    "current_company": "Most recent employer name verbatim, or null",
    "total_experience_years": 5.0,
    "seniority_level": "junior|mid|senior|staff|principal|lead|manager|director",
    "skills_technical": ["Python", "React", "AWS"],
    "skills_soft": ["leadership", "communication"],
    "tools": ["Git", "Docker", "JIRA"],
    "languages": ["English", "Spanish"],
    "experience": [
        {{
            "company": "Company Name",
            "role": "Job Title",
            "start_date": "2020-01",
            "end_date": "2023-06 or present",
            "duration_months": 42,
            "description": "Brief 1-2 sentence summary of responsibilities",
            "location": "City or Remote"
        }}
    ],
    "education": [
        {{
            "institution": "University Name",
            "degree": "Bachelor/Master/PhD",
            "field": "Computer Science",
            "year": 2018,
            "gpa": "3.8 or null"
        }}
    ],
    "certifications": [
        {{
            "name": "AWS Solutions Architect",
            "issuer": "Amazon",
            "year": 2022
        }}
    ],
    "projects": [
        {{
            "name": "Project Name",
            "description": "Brief description",
            "tech_stack": ["Python", "React"]
        }}
    ],
    "summary_short": "2-3 sentence professional summary",
    "summary_detailed": "Detailed 4-6 sentence profile summary covering strengths, experience, and career trajectory"
}}

RULES:
- Extract ALL skills mentioned (technical, tools, frameworks, languages)
- Calculate total_experience_years by summing all job durations
- Infer seniority_level from job titles and years of experience
- If a field is not found, use null for strings, [] for arrays, 0 for numbers
- Be thorough — don't miss skills mentioned in project descriptions"""

    result = llm_call(prompt, model=STRUCTURE_MODEL, temperature=0.1, max_tokens=3000)
    if not result:
        return _empty_result()

    return _parse_extraction(result)


def enrich_candidate(data: dict) -> dict:
    """Fill gaps and auto-tag the candidate profile."""
    # Fallback: derive current_role / current_company from experience[0] when LLM
    # produced a missing or obviously-bogus value (e.g. the literal "hire" or a
    # seniority-vote token like "strong_hire"). The first experience entry is
    # the most-recent job per prompt contract.
    _BAD_ROLE_TOKENS = {"hire", "no_hire", "strong_hire", "strong_no_hire",
                        "yes", "no", "n/a", "na", "none", "null", "unknown"}
    exp = data.get("experience") or []
    first_exp = exp[0] if exp and isinstance(exp[0], dict) else {}
    role_val = (data.get("current_role") or "").strip()
    if (not role_val) or role_val.lower() in _BAD_ROLE_TOKENS or len(role_val) < 3:
        fallback_role = (first_exp.get("role") or "").strip() or None
        data["current_role"] = fallback_role
    company_val = (data.get("current_company") or "").strip()
    if not company_val:
        data["current_company"] = (first_exp.get("company") or "").strip() or None

    # Infer seniority if missing
    if not data.get("seniority_level"):
        years = data.get("total_experience_years") or 0
        if years < 2:
            data["seniority_level"] = "junior"
        elif years < 5:
            data["seniority_level"] = "mid"
        elif years < 8:
            data["seniority_level"] = "senior"
        elif years < 12:
            data["seniority_level"] = "staff"
        else:
            data["seniority_level"] = "principal"

    # Calculate total experience if not set
    if not data.get("total_experience_years") and data.get("experience"):
        total_months = sum(
            e.get("duration_months", 0) for e in data["experience"]
            if isinstance(e, dict)
        )
        data["total_experience_years"] = round(total_months / 12, 1)

    # Auto-tag
    tags = set()

    # Tag by domain
    all_skills = " ".join(data.get("skills_technical", [])).lower()
    domain_tags = {
        "backend": ["python", "java", "go", "rust", "node", "django", "fastapi", "spring"],
        "frontend": ["react", "vue", "angular", "svelte", "typescript", "css", "tailwind"],
        "fullstack": [],
        "devops": ["docker", "kubernetes", "terraform", "ci/cd", "aws", "gcp", "azure"],
        "data": ["sql", "pandas", "spark", "airflow", "etl", "warehouse"],
        "ml-ai": ["pytorch", "tensorflow", "llm", "machine learning", "nlp", "computer vision"],
        "mobile": ["swift", "kotlin", "react native", "flutter", "ios", "android"],
    }

    for domain, keywords in domain_tags.items():
        if any(kw in all_skills for kw in keywords):
            tags.add(domain)

    # Check fullstack
    if "backend" in tags and "frontend" in tags:
        tags.add("fullstack")

    # Tag by seniority
    if data.get("seniority_level"):
        tags.add(data["seniority_level"])

    data["tags"] = list(tags)
    return data


def generate_qa_pairs(raw_text: str, name: str = "candidate") -> list[dict]:
    """Generate HyPE Q&A pairs for embedding."""
    if not raw_text or len(raw_text) < 100:
        return []

    prompt = f"""Generate 20-30 Q&A pairs about this candidate that a recruiter might ask.
Cover: skills, experience, education, projects, strengths, gaps.

CV TEXT:
{raw_text[:4000]}

Return ONLY a JSON array:
[
    {{"question": "Does this person have Python experience?", "answer": "Yes, 5 years of Python at Company X..."}},
    {{"question": "What is their education background?", "answer": "BS Computer Science from Stanford..."}},
    ...
]

RULES:
- Questions should be natural recruiter queries
- Answers should be specific with details from the CV
- Cover: technical skills, soft skills, years of experience, companies, education, certifications, projects
- Include questions about leadership, team size, domain expertise"""

    result = llm_call(prompt, model=LITE_MODEL, temperature=0.3, max_tokens=3000)
    if not result:
        return []

    try:
        json_match = re.search(r'\[[\s\S]*\]', result)
        if json_match:
            pairs = json.loads(json_match.group())
            return [p for p in pairs if isinstance(p, dict) and "question" in p and "answer" in p]
    except json.JSONDecodeError:
        logger.warning("Failed to parse Q&A pairs")

    return []


def compute_quality_score(data: dict) -> int:
    """Score CV completeness 0-100."""
    score = 0

    if data.get("name"): score += 10
    if data.get("email"): score += 5
    if data.get("phone"): score += 5
    if data.get("current_role"): score += 10
    if data.get("current_company"): score += 5

    skills = data.get("skills_technical", [])
    if len(skills) >= 5: score += 15
    elif len(skills) >= 2: score += 8

    exp = data.get("experience", [])
    if len(exp) >= 3: score += 15
    elif len(exp) >= 1: score += 8

    edu = data.get("education", [])
    if len(edu) >= 1: score += 10

    if data.get("certifications"): score += 5
    if data.get("projects"): score += 5
    if data.get("summary_short"): score += 5
    if data.get("total_experience_years"): score += 10

    return min(100, score)


def _parse_extraction(result: str) -> dict:
    """Parse LLM extraction result, handling malformed JSON."""
    try:
        json_match = re.search(r'\{[\s\S]*\}', result)
        if json_match:
            data = json.loads(json_match.group())
            # Ensure arrays are arrays
            for field in ("skills_technical", "skills_soft", "tools", "languages", "experience",
                          "education", "certifications", "projects"):
                if not isinstance(data.get(field), list):
                    data[field] = []
            return data
    except json.JSONDecodeError:
        logger.warning("Failed to parse CV extraction JSON, attempting repair")

    # Attempt basic repair
    try:
        # Remove trailing garbage
        cleaned = result.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("```")[1]
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
        json_match = re.search(r'\{[\s\S]*\}', cleaned)
        if json_match:
            return json.loads(json_match.group())
    except (json.JSONDecodeError, IndexError):
        pass

    logger.error("CV extraction parse failed completely")
    return _empty_result()


def _empty_result() -> dict:
    return {
        "name": "Unknown",
        "email": None, "phone": None, "location": None, "linkedin_url": None,
        "current_role": None, "current_company": None,
        "total_experience_years": 0, "seniority_level": None,
        "skills_technical": [], "skills_soft": [], "tools": [], "languages": [],
        "experience": [], "education": [], "certifications": [], "projects": [],
        "summary_short": None, "summary_detailed": None,
    }
