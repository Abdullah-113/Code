import streamlit as st
import pdfplumber
import fitz  # PyMuPDF
import os
import json
import re
import requests
from dotenv import load_dotenv
from google import genai

# ================= ENV =================
load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
N8N_WEBHOOK_URL = os.getenv("N8N_WEBHOOK_URL")

client = genai.Client(api_key=GEMINI_API_KEY)


# ================= SAFE JSON PARSER =================
def safe_json_parse(text: str):
    """
    Safely extract JSON from Gemini output.
    Keeps ALL fields returned by Gemini.
    """
    cleaned = text.replace("```json", "").replace("```", "").strip()
    match = re.search(r"\{[\s\S]*\}", cleaned)
    if not match:
        raise ValueError("No JSON object found in Gemini output")
    return json.loads(match.group())


# ================= FILE HELPERS =================
def extract_text_from_pdf(file):
    text = ""
    try:
        with pdfplumber.open(file) as pdf:
            for page in pdf.pages:
                text += page.extract_text() or ""
    except Exception:
        pdf = fitz.open(stream=file.read(), filetype="pdf")
        for page in pdf:
            text += page.get_text()
    return text.strip()


def extract_text_from_txt(file):
    return file.read().decode("utf-8").strip()


# ================= GEMINI ANALYSIS =================
def analyze_resume_vs_jd(resume_text, jd_text):
    prompt = f"""
STRICT RULES:
- Return ONLY valid JSON
- Start with {{ and end with }}
- No markdown
- No explanation

FORMAT:
{{
  "match_score": 0-100,
  "matched_skills": [],
  "missing_skills": [],
  "experience_fit": "LOW | MEDIUM | HIGH",
  "recommendation": "APPLY | SKIP",
  "summary": ""
}}

RESUME:
\"\"\"{resume_text[:4000]}\"\"\"

JOB DESCRIPTION:
\"\"\"{jd_text[:4000]}\"\"\"
"""
    response = client.models.generate_content(
        model="gemini-3-flash-preview",
        contents=prompt,
    )
    return response.text.strip()


# ================= STREAMLIT UI =================
st.set_page_config(
    page_title="AI Job Application Orchestrator",
    page_icon="📄",
    layout="wide",
)

st.title("📄 AI Job Application Orchestrator")
st.caption("Full JSON preserved • Gemini + n8n + Google Sheets")
st.divider()

# ================= INPUTS =================
st.subheader("👤 Candidate & Job Details")
c1, c2, c3, c4 = st.columns(4)

candidate_name = c1.text_input("Candidate Name")
company = c2.text_input("Company")
role = c3.text_input("Role")
recruiter_email = c4.text_input("Recruiter Email")

left, right = st.columns(2)

with left:
    resume_file = st.file_uploader("Upload Resume (PDF / TXT)", type=["pdf", "txt"])
    resume_text = ""
    if resume_file:
        if resume_file.type == "application/pdf":
            resume_text = extract_text_from_pdf(resume_file)
        else:
            resume_text = extract_text_from_txt(resume_file)
        st.success("Resume loaded")

with right:
    jd_text = st.text_area("Paste Job Description", height=260)

# ================= ACTION =================
if st.button("🚀 Analyze & Send to n8n", use_container_width=True):

    if not all(
        [candidate_name, company, role, recruiter_email, resume_text, jd_text.strip()]
    ):
        st.warning("Please fill all fields and upload resume.")
        st.stop()

    # ---------- Gemini ----------
    with st.spinner("🤖 Gemini analyzing..."):
        raw_output = analyze_resume_vs_jd(resume_text, jd_text)

    # Show raw response
    with st.expander("🧪 Raw Gemini Output"):
        st.code(raw_output)

    try:
        result_json = safe_json_parse(raw_output)
    except Exception as e:
        st.error("❌ Gemini response is not valid JSON")
        st.exception(e)
        st.stop()

    # ---------- DISPLAY FULL JSON ----------
    st.success("✅ Gemini JSON Parsed Successfully")
    st.subheader("📦 Full Gemini JSON")
    st.json(result_json)

    # ---------- OPTIONAL UI INSIGHTS ----------
    st.metric("Match Score", f"{result_json.get('match_score', 0)}%")
    st.info(f"Recommendation: {result_json.get('recommendation', 'N/A')}")
    st.write("### Summary")
    st.write(result_json.get("summary", ""))

    # ---------- PAYLOAD TO n8n (FULL JSON KEPT) ----------
    payload = {
        "candidate_name": candidate_name,
        "company": company,
        "role": role,
        "recruiter_email": recruiter_email,
        "gemini_result": result_json,  # 🔥 FULL JSON PASSED AS-IS
    }

    # ---------- SEND TO n8n (ASYNC SAFE) ----------
    st.subheader("📨 Automation Status")

    try:
        requests.post(
            N8N_WEBHOOK_URL,
            json=payload,
            timeout=5,
        )
        st.success("✅ Request sent to n8n. Processing in background.")
    except requests.exceptions.ReadTimeout:
        st.success("✅ Request accepted by n8n. Processing in background.")
    except requests.exceptions.RequestException as e:
        st.error("❌ Failed to reach n8n")
        st.exception(e)
        st.stop()

    st.info("📊 Check Google Sheets & Email for final result")
