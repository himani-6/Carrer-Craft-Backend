# backend/ats_utils/ats_ai.py
import os
import json
import requests
from dotenv import load_dotenv

# Keep optional Groq SDK import harmless (we won't use it)
try:
    from groq import Groq  # optional, not used
except Exception:
    Groq = None

load_dotenv()

# Environment (use GROQ_API_KEY / GROQ_API_URL; tolerate old GORQ names)
API_KEY = os.getenv("GROQ_API_KEY") 
# Default to the REST base used by your JobMatcher (this is important)
GROQ_API_URL = os.getenv("GROQ_API_URL") or "https://api.groq.com/openai/v1"
MODEL = os.getenv("GROQ_MODEL") or "llama-3.1-8b-instant"

# DEBUG print to confirm API key loaded
print("DEBUG --- ATS API KEY LOADED:", API_KEY)
print("DEBUG --- ATS USING REST URL:", GROQ_API_URL)
print("DEBUG --- ATS MODEL:", MODEL)

# ----------------------------
# JSON utilities and prompts (UNCHANGED)
# ----------------------------
BASE_JSON = """
{
  "score": 0,
  "matched_keywords": [],
  "missing_keywords": [],
  "formatting_issues": [],
  "suggestions": [],
  "strengths": [],

  "extracted": {
      "name": "",
      "email": "",
      "position": "",
      "experience": "Fresher",
      "skills": []
  },

  "grammatical_errors": [],
  "professional_tone": "",
  "unnecessary_info": [],
  "experience_relevance": "",
  "skills_relevance": {
      "matched": [],
      "missing": []
  }
}
"""


def _safe_parse_json(raw: str):
    """
    Try to parse JSON. If it fails, try to extract the JSON substring.
    Returns dict or None.
    """
    if raw is None:
        return None

    raw = raw.strip()

    # First attempt
    try:
        return json.loads(raw)
    except Exception:
        pass

    # Second attempt: extract substring between first '{' and last '}'
    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(raw[start : end + 1])
        except Exception:
            return None

    return None


def _merge_defaults(data: dict, jd_present: bool) -> dict:
    """
    Ensure all expected keys exist so the frontend never breaks.
    Also enforces rules for missing_keywords when there is no JD.
    """
    defaults = {
        "score": 50,
        "matched_keywords": [],
        "missing_keywords": [],
        "formatting_issues": [],
        "suggestions": [],
        "strengths": [],
        "extracted": {
            "name": "",
            "email": "",
            "position": "",
            "experience": "Fresher",
            "skills": [],
        },
        "grammatical_errors": [],
        "professional_tone": "",
        "unnecessary_info": [],
        "experience_relevance": "",
        "skills_relevance": {
            "matched": [],
            "missing": [],
        },
    }

    if not isinstance(data, dict):
        data = {}

    # Top-level defaults
    for key, val in defaults.items():
        if key not in data:
            data[key] = val

    # Ensure nested dicts
    if not isinstance(data.get("extracted"), dict):
        data["extracted"] = {}
    if not isinstance(data.get("skills_relevance"), dict):
        data["skills_relevance"] = {}

    # Ensure extracted subkeys
    for sub_key, sub_val in defaults["extracted"].items():
        if sub_key not in data["extracted"]:
            data["extracted"][sub_key] = sub_val

    # Ensure skills_relevance subkeys
    for sub_key, sub_val in defaults["skills_relevance"].items():
        if sub_key not in data["skills_relevance"]:
            data["skills_relevance"][sub_key] = sub_val

    # If there is NO JD, nothing is "missing"
    if not jd_present:
        data["missing_keywords"] = []
        data["skills_relevance"]["missing"] = []

        # Target position MUST be empty when no JD (as per requirement)
        data["extracted"]["position"] = ""

    return data


# ------------------------
# Prompts (UNCHANGED)
# ------------------------
def build_resume_only_prompt(resume_text: str):
    return f"""
You are an expert Applicant Tracking System (ATS). Only the resume is provided (NO job description).

Return ONLY valid JSON with no extra text. It MUST match this schema:

{BASE_JSON}

========================
SCORING (RESUME ONLY)
========================
- "score": integer 0–100.
- This score reflects overall resume quality for generic tech/software roles.
- Use BALANCED, REALISTIC scoring:
    • Strong fresher resume: 65–80
    • Average: 45–65
    • Weak: below 45

========================
KEYWORDS & SKILLS
========================
- "matched_keywords": skills present in resume
- "missing_keywords": MUST be []
- "skills_relevance.missing": MUST be []
- "skills_relevance.matched": skills in resume

========================
EXTRACTED SECTION
========================
- "extracted.name": candidate name
- "extracted.email": candidate email
- "extracted.position": "" (NO JD)
- "extracted.experience": "Fresher" or number of years
- "extracted.skills": 5–10 skills

========================
GRAMMAR vs FORMATTING
========================
- real grammar issues only
- spacing/layout issues belong in formatting_issues

========================
RESUME BELOW
========================

{resume_text}
"""


def build_resume_jd_prompt(resume_text: str, jd: str):
    return f"""
You are an Applicant Tracking System (ATS) evaluating ONE candidate for ONE specific job.

Return ONLY valid JSON with no extra text. Use this schema:

{BASE_JSON}

========================
SCORING WITH JOB DESCRIPTION
========================
- "score": 0–100 based on resume match to JD
- realistic ATS scoring required:
    • Excellent: 80–95
    • Good: 65–80
    • Average: 45–65
    • Poor: <45

========================
MATCHED & MISSING KEYWORDS
========================
- matched_keywords = skills in BOTH resume & JD
- missing_keywords = required in JD but missing in resume
- skills_relevance must match this logic

========================
POSITION & EXPERIENCE
========================
- extracted.position = main JD role
- experience mapping same as before

========================

RESUME:
{resume_text}

JOB DESCRIPTION:
{jd}
"""


# ------------------------
# REST call wrappers (use requests to call same endpoint as JobMatcher)
# ------------------------
def _call_model_chat(prompt: str, model_name: str = MODEL, temperature: float = 0.2):
    """
    Use the exact same working Groq REST call as JobMatcher.
    This is guaranteed to work because JobMatcher works perfectly.
    """
    if not API_KEY:
        raise RuntimeError("No GROQ API key configured")

    # EXACT same URL JobMatcher uses (your working one)
    url = "https://api.groq.com/openai/v1/chat/completions"

    payload = {
        "model": model_name,
        "messages": [
            {"role": "user", "content": prompt}
        ],
        "max_tokens": 1500,
        "temperature": temperature
    }

    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }

    resp = requests.post(url, json=payload, headers=headers, timeout=30)
    resp.raise_for_status()
    return resp.json()


def _model_response_to_text(response):
    """
    Normalize response JSON similar to JobMatcher: try choices[0].message.content, fallback to text/output.
    """
    try:
        choices = response.get("choices") or []
        if choices:
            first = choices[0]
            # chat-style responses may have message -> content
            msg = first.get("message") or {}
            content = msg.get("content") or first.get("text") or ""
            if content:
                return content
        return response.get("output") or response.get("result") or str(response)
    except Exception:
        return str(response)


def _analyze_with_model(prompt: str, resume_text: str, jd_present: bool):
    """
    Primary call path that uses the REST endpoint. Returns parsed dict or None + raw response.
    """
    raw_resp = _call_model_chat(prompt)
    text = _model_response_to_text(raw_resp)
    parsed = _safe_parse_json(text)
    if parsed is None:
        # try extracting JSON substring
        parsed = _safe_parse_json(text)
    if parsed is None:
        return None, raw_resp
    parsed = _merge_defaults(parsed, jd_present)
    return parsed, raw_resp


# ------------------------
# Public functions used by backend (UNCHANGED logic)
# ------------------------
def _analyze_resume_only(resume_text: str) -> dict:
    """
    Evaluate resume WITHOUT job description.
    """
    prompt = build_resume_only_prompt(resume_text)

    # If API available -> try model; otherwise fallback
    if API_KEY:
        try:
            parsed, raw = _analyze_with_model(prompt, resume_text, jd_present=False)
            if parsed is not None:
                return parsed
        except Exception as e:
            print("Groq model failed for resume-only:", e)

    # fallback simple heuristic (unchanged)
    words = resume_text.lower().split()
    skills = [w for w in ["python", "java", "sql", "javascript", "react", "aws", "docker", "c++", "c"] if w in words]
    fallback = {
        "score": 55,
        "matched_keywords": skills[:5],
        "missing_keywords": [],
        "formatting_issues": [],
        "suggestions": ["Use relevant keywords from job description", "Improve bullet clarity"],
        "strengths": ["Education present", "Projects listed"],
        "extracted": {"name": "", "email": "", "position": "", "experience": "1-2 years" if len(words) > 40 else "Fresher", "skills": skills[:5]},
        "grammatical_errors": [],
        "professional_tone": "",
        "unnecessary_info": [],
        "experience_relevance": "",
        "skills_relevance": {"matched": skills[:3], "missing": []},
        "error": "fallback_used"
    }
    return _merge_defaults(fallback, jd_present=False)


def analyze_resume_with_ai(resume_text: str, job_description: str):
    """
    Main function used by FastAPI backend.
    If JD is present -> strict ATS match.
    If JD is empty -> resume-only evaluation.
    """
    jd = (job_description or "").strip()
    if not jd:
        return _analyze_resume_only(resume_text)

    prompt = build_resume_jd_prompt(resume_text, jd)

    if API_KEY:
        try:
            parsed, raw = _analyze_with_model(prompt, resume_text, jd_present=True)
            if parsed is not None:
                return parsed
        except Exception as e:
            print("Groq model failed for resume+JD:", e)

    # fallback to resume-only analysis if JD-mode failed
    return _analyze_resume_only(resume_text)
