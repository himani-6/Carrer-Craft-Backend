import os
import requests
import tempfile
from dotenv import load_dotenv
from ats_utils.extract_any import extract_text_from_file

load_dotenv()

# ADZUNA env names used here
ADZUNA_APP_ID = os.getenv("ADZUNA_APP_ID")
ADZUNA_APP_KEY = os.getenv("ADZUNA_APP_KEY")


GORQ_API_KEY = os.getenv("GORQ_API_KEY") 
GORQ_API_URL = os.getenv("GORQ_API_URL") or "https://api.groq.com/openai/v1"
GORQ_MODEL = os.getenv("GORQ_MODEL") or "llama-3.1-8b-instant"


def get_text_from_upload(file_obj, filename):
    # Cross-platform temporary file location
    tmp_dir = tempfile.gettempdir()
    tmp_path = os.path.join(tmp_dir, filename)

    # file_obj might be a BytesIO or file-like
    try:
        # If file_obj has .read() directly (BytesIO or UploadFile-like)
        data = file_obj.read()
    except Exception:
        # If file_obj is already bytes
        data = file_obj

    with open(tmp_path, "wb") as f:
        f.write(data)

    text = extract_text_from_file(tmp_path)

    try:
        os.remove(tmp_path)
    except Exception:
        pass

    return text


def call_gorc_model(prompt: str):
    """
    Uses Chat Completions endpoint for job matcher.
    Expects GORQ_API_URL to be a base like: https://api.groq.com/openai/v1
    and will POST to {GORQ_API_URL}/chat/completions
    """
    if not GORQ_API_KEY or not GORQ_API_URL:
        raise RuntimeError("GORQ_API_KEY or GORQ_API_URL not configured")

    url = f"{GORQ_API_URL}/chat/completions"

    payload = {
        "model": GORQ_MODEL,
        "messages": [
            {"role": "user", "content": prompt}
        ],
        "max_tokens": 500,
        "temperature": 0.2
    }

    headers = {
        "Authorization": f"Bearer {GORQ_API_KEY}",
        "Content-Type": "application/json"
    }

    r = requests.post(url, json=payload, headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()


def make_ai_prompt(text, job_title, location, job_type, experience):
    return f"""
You are an AI job role recommender.

User resume:
'''{text[:4000]}'''

Desired Job Title: {job_title}
Location: {location}
Job Type: {job_type}
Experience: {experience}

Return ONLY JSON:

{{
 "recommendations": [
   {{
     "title": "Software Developer",
     "description": "Short description",
     "level": "Entry",
     "skills": ["Python", "SQL", "APIs"]
   }}
 ]
}}
"""


def fetch_adzuna_jobs(job_title, location, page=1, results_per_page=10):
    country = "in"
    url = f"https://api.adzuna.com/v1/api/jobs/{country}/search/{page}"

    params = {
        "app_id": ADZUNA_APP_ID,
        "app_key": ADZUNA_APP_KEY,
        "what": job_title,
        "where": location,
        "results_per_page": results_per_page,
    }

    r = requests.get(url, params=params, timeout=15)
    r.raise_for_status()

    data = r.json()
    jobs = []

    for j in data.get("results", []):
        jobs.append({
            "title": j.get("title"),
            "company": j.get("company", {}).get("display_name") if j.get("company") else None,
            "location": j.get("location", {}).get("display_name") if j.get("location") else None,
            "salary_min": j.get("salary_min"),
            "salary_max": j.get("salary_max"),
            "redirect_url": j.get("redirect_url"),
            "created": j.get("created"),
            "description": j.get("description"),
        })

    return jobs
