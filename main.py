# backend/main.py
import os
import fitz
import docx
import traceback
from io import BytesIO
from fastapi import FastAPI, UploadFile, Form, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from firebase_admin_config import db
from datetime import datetime
import uuid

# Try to import the ATS analyzer (which we've placed at ats_utils/ats_ai.py)
try:
    from ats_utils.ats_ai import analyze_resume_with_ai
    print("Loaded ats_utils.ats_ai analyzer")
except Exception:
    # fallback analyzer if ats_ai isn't available (keeps UI functional)
    def analyze_resume_with_ai(resume_text: str, job_description: str):
        words = resume_text.lower().split()
        skills = [w for w in ["python", "java", "sql", "javascript", "react", "docker", "aws", "c++", "c"] if w in words]
        return {
            "score": 60,
            "matched_keywords": skills[:5],
            "missing_keywords": [],
            "formatting_issues": [],
            "suggestions": ["Add more keywords from job description", "Make project bullets quantifiable"],
            "strengths": ["Clear education section", "Relevant projects"],
            "extracted": {
                "name": "",
                "email": "",
                "position": "" if not job_description else job_description.split("\n")[0][:50],
                "experience": "Fresher" if len(words) < 50 else "1-2 years",
                "skills": skills[:5]
            },
            "grammatical_errors": [],
            "professional_tone": "",
            "unnecessary_info": [],
            "experience_relevance": "",
            "skills_relevance": {"matched": skills[:3], "missing": []}
        }

# Job matcher functions are in jobmatcher.py (unchanged)
from jobmatcher import (
    get_text_from_upload,
    make_ai_prompt,
    call_gorc_model,
    fetch_adzuna_jobs
)

app = FastAPI()

# ------------------------------
# CORS
# ------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ------------------------------
# PDF & DOCX extraction helpers
# ------------------------------
def extract_text_from_pdf(file_path):
    text = ""
    with fitz.open(file_path) as pdf:
        for page in pdf:
            page_text = page.get_text("text")
            if not page_text.strip():
                blocks = page.get_text("blocks")
                if isinstance(blocks, list):
                    page_text = " ".join([blk[4] for blk in blocks if len(blk) > 4])
            text += page_text + "\n"
    return text.strip()


def extract_text_from_docx(file_path):
    doc = docx.Document(file_path)
    lines = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
    return "\n".join(lines)


# ------------------------------
# ATS ANALYSIS ROUTE (uses analyze_resume_with_ai from ats_utils)
# ------------------------------
@app.post("/ats-analyze")
async def ats_analyze(
    file: UploadFile = File(...),
    job_description: str = Form(""),
    userId: str = Form("")      # frontend should pass user.uid here
):
    file_ext = file.filename.split(".")[-1].lower()
    temp_path = f"temp.{file_ext}"

    # save uploaded file to temp
    with open(temp_path, "wb") as f:
        f.write(await file.read())

    # extract resume text
    try:
        if file_ext == "pdf":
            resume_text = extract_text_from_pdf(temp_path)
        elif file_ext == "docx":
            resume_text = extract_text_from_docx(temp_path)
        else:
            try:
                from ats_utils.extract_any import extract_text_from_file
                resume_text = extract_text_from_file(temp_path)
            except Exception:
                raise HTTPException(400, "Unsupported file format")
    except Exception as e:
        try:
            os.remove(temp_path)
        except:
            pass
        raise HTTPException(500, f"Failed to extract resume text: {e}")

    if len(resume_text) < 50:
        resume_text = "ERROR: Could not extract readable resume text."

    # call analyzer (existing function)
    try:
        result = analyze_resume_with_ai(resume_text, job_description)
    except Exception as e:
        traceback.print_exc()
        result = {
            "score": 0,
            "matched_keywords": [],
            "missing_keywords": [],
            "formatting_issues": [],
            "suggestions": [],
            "strengths": [],
            "extracted": {"name": "", "email": "", "position": "", "experience": "Fresher", "skills": []},
            "grammatical_errors": [],
            "professional_tone": "",
            "unnecessary_info": [],
            "experience_relevance": "",
            "skills_relevance": {"matched": [], "missing": []},
            "error": f"analyzer_failed: {str(e)}"
        }

    # cleanup temp file
    try:
        os.remove(temp_path)
    except:
        pass

    # create a new doc id and save FULL result in Firestore
    ats_id = str(uuid.uuid4())
    doc_data = {
        "id": ats_id,
        "userId": userId,
        "score": result.get("score", 0),
        "createdAt": datetime.utcnow(),
        "result": result
    }

    # write to Firestore
    try:
        db.collection("atsHistory").document(ats_id).set(doc_data)
    except Exception as e:
        print("Failed to write ATS history to Firestore:", e)

    # return id + result to frontend
    return {"id": ats_id, "result": result}


# ------------------------------
# AI RECOMMENDATION ROUTE (JobMatcher) - chat-style via jobmatcher.call_gorc_model
# ------------------------------
@app.post("/api/ai-recommend")
async def ai_recommend(
    resume: UploadFile = File(None),
    job_title: str = Form(...),
    location: str = Form(""),
    job_type: str = Form(""),
    experience: str = Form("")
):
    try:
        extracted_text = ""

        # Extract resume text if uploaded
        if resume:
            content = await resume.read()
            extracted_text = get_text_from_upload(BytesIO(content), resume.filename)

        # Build prompt
        prompt = make_ai_prompt(
            extracted_text,
            job_title,
            location,
            job_type,
            experience
        )

        # Call JobMatcher (chat) -- call_gorc_model is implemented in jobmatcher.py
        resp = call_gorc_model(prompt)

        # Normalize output and extract JSON substring
        try:
            choices = resp.get("choices") or []
            if choices:
                first = choices[0]
                text_out = first.get("message", {}).get("content") or first.get("text") or ""
            else:
                text_out = resp.get("output") or resp.get("result") or str(resp)
        except Exception:
            text_out = str(resp)

        import json, re
        m = re.search(r"\{[\s\S]*\}|\[[\s\S]*\]", text_out)
        if not m:
            return {"raw": text_out, "full_response": resp}

        parsed = json.loads(m.group(0))
        return {"recommendations": parsed.get("recommendations", parsed)}
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


# ------------------------------
# LIVE JOB FETCHING (Adzuna)
# ------------------------------
@app.post("/api/live-jobs")
async def live_jobs(
    job_title: str = Form(...),
    location: str = Form(""),
    page: int = Form(1)
):
    try:
        jobs = fetch_adzuna_jobs(
            job_title=job_title,
            location=location,
            page=page
        )
        return {"jobs": jobs}
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

