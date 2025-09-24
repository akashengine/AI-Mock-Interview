import os, json, base64, textwrap, time, datetime as dt
from typing import Any, Dict, List
import streamlit as st, requests, pandas as pd
import tempfile, webbrowser

# App Configuration
APP_TITLE = "Drishti UPSC Mock Interview"
APP_SUBTITLE = "Secure AI-Powered Interview Platform"
VAPI_BASE_URL = "https://api.vapi.ai"

# Load environment variables
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

def get_secret(key: str, default: str = "") -> str:
    """Get secret from Streamlit secrets or environment variables"""
    try:
        return st.secrets.get(key, os.getenv(key, default))
    except Exception:
        return os.getenv(key, default)

# Get all secrets
APP_PASSWORD = get_secret("APP_PASSWORD", "")
VAPI_API_KEY = get_secret("VAPI_API_KEY", "")
VAPI_PUBLIC_KEY = get_secret("VAPI_PUBLIC_KEY", "")
GEMINI_API_KEY = get_secret("GEMINI_API_KEY", "")
GITHUB_TOKEN = get_secret("GITHUB_TOKEN", "")

# Page configuration
st.set_page_config(
    page_title=APP_TITLE,
    page_icon="🎤",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Hide sidebar completely
st.markdown("""
<style>
    .css-1d391kg {display: none}
    .st-emotion-cache-6qob1r {display: none}
    [data-testid="stSidebar"] {display: none}
    .sidebar .sidebar-content {display: none}
</style>
""", unsafe_allow_html=True)

# Initialize session state
def initialize_session_state():
    """Initialize all session state variables"""
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False
    if "candidate_json" not in st.session_state:
        st.session_state.candidate_json = None
    if "assistants" not in st.session_state:
        st.session_state.assistants = {}
    if "current_candidate" not in st.session_state:
        st.session_state.current_candidate = None
    if "interview_started_at" not in st.session_state:
        st.session_state.interview_started_at = None
    if "interview_status" not in st.session_state:
        st.session_state.interview_status = "idle"
    if "deployed_interview" not in st.session_state:
        st.session_state.deployed_interview = None

initialize_session_state()

# Authentication
def authenticate():
    """Handle password authentication"""
    if not APP_PASSWORD:
        st.error("Application password not configured in secrets.")
        st.stop()
    
    st.title("🔐 Secure Access")
    st.markdown("### UPSC Mock Interview Platform")
    
    password = st.text_input("Enter access password:", type="password")
    
    if st.button("Login", type="primary"):
        if password == APP_PASSWORD:
            st.session_state.authenticated = True
            st.success("Authentication successful!")
            st.rerun()
        else:
            st.error("Invalid password. Access denied.")

if not st.session_state.authenticated:
    authenticate()
    st.stop()

# Main App Header
st.title(APP_TITLE)
st.caption(APP_SUBTITLE)
st.markdown("---")

# Check API Configuration
def check_api_configuration():
    """Check if all required API keys are configured"""
    missing_keys = []
    
    if not VAPI_API_KEY:
        missing_keys.append("VAPI_API_KEY")
    if not VAPI_PUBLIC_KEY:
        missing_keys.append("VAPI_PUBLIC_KEY")
    if not GEMINI_API_KEY:
        missing_keys.append("GEMINI_API_KEY")
    if not GITHUB_TOKEN:
        missing_keys.append("GITHUB_TOKEN")
    
    if missing_keys:
        st.error(f"Missing required API keys: {', '.join(missing_keys)}")
        st.info("Please configure these keys in Streamlit secrets or environment variables.")
        return False
    
    st.success("✅ All API keys configured")
    return True

if not check_api_configuration():
    st.stop()

# Gemini Client
_GEMINI_CLIENT = None

def get_gemini_client():
    """Initialize Gemini client"""
    global _GEMINI_CLIENT
    if _GEMINI_CLIENT is None:
        import google.generativeai as genai
        genai.configure(api_key=GEMINI_API_KEY)
        _GEMINI_CLIENT = genai
    return _GEMINI_CLIENT

def extract_candidate_json(files: List[Dict[str, Any]], reg_no: str) -> Dict[str, Any]:
    """Extract candidate information from DAF files using Gemini"""
    genai = get_gemini_client()
    model = genai.GenerativeModel("gemini-1.5-flash")
    
    schema = {
        "name": "string", "roll_no": "string", "dob": "string", "gender": "string",
        "community": "string", "religion": "string", "mother_tongue": "string",
        "birth_place": "string", "home_city": "string", "marital_status": "string",
        "employment_status": "string", "number_of_attempts": "integer",
        "service_preferences": "array", "cadre_preferences": "array",
        "assets": "string", "education": "object", "optional_subject": "string",
        "language_medium": "string", "hobbies": "array", "achievements": "array",
        "parents": "object", "address": "object", "email": "string", "phone": "string",
        "work_experience": "array", "positions_of_responsibility": "array",
        "extracurriculars": "array", "sports": "array", "certifications": "array",
        "awards": "array", "languages_known": "array",
        "preferred_languages_for_interview": "array", "coaching": "string",
        "career_gap_explanations": "string", "notable_projects": "array",
        "publications": "array", "social_work": "array", "disciplinary_actions": "string"
    }
    
    sys_prompt = f"""You are an expert UPSC DAF parser. Extract a single JSON from DAF-1 and DAF-2 following this schema:
{json.dumps(schema, indent=2)}

Candidate roll/registration no.: {reg_no or 'UNKNOWN'}

Rules:
- Return valid JSON only
- Populate all available fields from the documents
- If a field is absent, omit it from the JSON
- Extract detailed information for all arrays and objects"""
    
    parts = [{"text": sys_prompt}]
    for f in files:
        b64 = base64.b64encode(f["bytes"]).decode()
        parts.append({"inline_data": {"mime_type": f["mime_type"], "data": b64}})
    
    response = model.generate_content(parts)
    
    # Parse JSON from response
    text = (response.text or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
    
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        text = text[start:end+1]
    
    data = json.loads(text)
    if not data.get("roll_no"):
        data["roll_no"] = reg_no
    
    return data

def get_mime_type(filename: str) -> str:
    """Get MIME type from filename"""
    ext = filename.split(".")[-1].lower()
    mime_types = {
        "pdf": "application/pdf",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "png": "image/png"
    }
    return mime_types.get(ext, "application/octet-stream")

# Step 1: Candidate Input
st.header("Step 1: Candidate Information")

col1, col2 = st.columns(2)

with col1:
    reg_no = st.text_input("Registration / Roll Number", placeholder="Enter candidate roll number")

with col2:
    st.write(" ")  # Spacing

daf1_file = st.file_uploader("Upload DAF-1 (PDF/Image)", type=["pdf", "png", "jpg", "jpeg"])
daf2_file = st.file_uploader("Upload DAF-2 (PDF/Image)", type=["pdf", "png", "jpg", "jpeg"])

if st.button("Extract Candidate Information", type="primary"):
    if not (daf1_file and daf2_file):
        st.error("Please upload both DAF-1 and DAF-2 files.")
    else:
        files_for_processing = []
        for file in [daf1_file, daf2_file]:
            file_bytes = file.read()
            files_for_processing.append({
                "bytes": file_bytes,
                "mime_type": get_mime_type(file.name),
                "filename": file.name
            })
        
        try:
            with st.spinner("Extracting candidate information..."):
                st.session_state.candidate_json = extract_candidate_json(files_for_processing, reg_no)
            st.success("✅ Candidate information extracted successfully!")
        except Exception as e:
            st.error(f"❌ Extraction failed: {e}")

st.markdown("---")

# Step 2: Review Candidate Information
st.header("Step 2: Review Candidate Information")

if st.session_state.candidate_json:
    editable_json = st.text_area(
        "Candidate Information (JSON - Editable)",
        value=json.dumps(st.session_state.candidate_json, indent=2, ensure_ascii=False),
        height=300
    )
    
    if st.button("Update Information"):
        try:
            st.session_state.candidate_json = json.loads(editable_json)
            st.success("✅ Candidate information updated.")
        except Exception as e:
            st.error(f"❌ Invalid JSON format: {e}")
else:
    st.info("Please complete Step 1 to extract candidate information.")

st.markdown("---")

# Step 3: Create Assistant
st.header("Step 3: Create Interview Assistant")

def create_interview_prompt(candidate_data: Dict[str, Any]) -> str:
    """Create interview prompt based on candidate data"""
    name = candidate_data.get("name", "Candidate")
    roll_no = candidate_data.get("roll_no", "")
    
    prompt = f"""[Identity]
You are a UPSC Interview Board Member conducting the Civil Services Personality Test.
Role: Senior bureaucrat/academician, neutral and impartial.
Purpose: To simulate a 30-35 minute UPSC Personality Test Interview for candidate {name} (Roll No: {roll_no}), followed by 5 minutes of feedback.

[Style]
- Formal, dignified, polite, and probing
- Neutral and impartial
- Adaptive: switch roles between Chair and Subject-Matter Experts
- Build follow-up questions from candidate's answers

[Response Guidelines]
- Ask one clear question at a time (The question must not be too long)
- If vague → ask for specifics
- If fact-only → seek opinion/analysis
- If hesitant → reassure
- If extreme view → present counterview
- Always stay courteous
- Do be either too positive or too negative

[Interview Flow]
1) Opening (2 min)
2) DAF-based Background (8-10 min)
3) Academic & Optional Subject (8-10 min)
4) Hobbies, ECAs & Personality (5-7 min)
5) Current Affairs & Governance (7-8 min)
6) Closing (2 min)
7) Feedback (5 min)

[Error Handling]
- If candidate says "I don't know" accept gracefully
- If candidate misunderstands politely clarify

[Candidate Information]
{json.dumps(candidate_data, indent=2, ensure_ascii=False)}"""
    
    return prompt

def create_vapi_assistant(name: str, system_prompt: str, roll_no: str) -> str:
    """Create Vapi assistant and return assistant ID"""
    url = f"{VAPI_BASE_URL}/assistant"
    headers = {
        "Authorization": f"Bearer {VAPI_API_KEY}",
        "Content-Type": "application/json"
    }
    
    # Analysis plan for structured feedback
    summary_messages = [
        {
            "role": "system",
            "content": "You are an expert note-taker. Summarize the interview call in 2-3 sentences, highlighting key topics/questions asked and candidate's response areas (background, current affairs, ethics, optional subject, hobbies)."
        },
        {
            "role": "user",
            "content": "Here is the transcript:\n\n{{transcript}}\n\nHere is the ended reason of the call:\n\n{{endedReason}}"
        }
    ]
    
    structured_schema = {
        "type": "object",
        "properties": {
            "clarityOfExpression": {"type": "string"},
            "reasoningAbility": {"type": "string"},
            "analyticalDepth": {"type": "string"},
            "currentAffairsAwareness": {"type": "string"},
            "ethicalJudgment": {"type": "string"},
            "personalityTraits": {"type": "string"},
            "socialAwareness": {"type": "string"},
            "hobbiesDepth": {"type": "string"},
            "overallImpression": {"type": "string"},
            "strengths": {"type": "string"},
            "areasForImprovement": {"type": "string"},
            "overallFeedback": {"type": "string"}
        }
    }
    
    structured_messages = [
        {
            "role": "system",
            "content": f"Extract structured interview performance data. Each field should contain qualitative comments (2-3 sentences max). Output JSON with all fields populated.\n\nSchema:\n{json.dumps(structured_schema)}"
        },
        {
            "role": "user",
            "content": "Here is the transcript:\n\n{{transcript}}\n\nHere is the ended reason of the call:\n\n{{endedReason}}"
        }
    ]
    
    success_messages = [
        {
            "role": "system",
            "content": "Evaluate the interview success based on: 1) Clarity of Expression, 2) Reasoning & Analytical Depth, 3) Current Affairs & Governance Awareness, 4) Ethical & Situational Judgment, 5) Personality Traits & Social Awareness. Provide overall rating: Highly Suitable/Suitable/Borderline/Unsuitable with brief justification."
        },
        {
            "role": "user",
            "content": "Here is the transcript:\n\n{{transcript}}\n\nHere is the ended reason:\n\n{{endedReason}}\n\nHere was the system prompt:\n\n{{systemPrompt}}"
        }
    ]
    
    payload = {
        "name": name,
        "voice": {
            "provider": "11labs",
            "model": "eleven_multilingual_v2",
            "voiceId": "xZp4zaaBzoWhWxxrcAij",
            "stability": 0.5,
            "similarityBoost": 0.75
        },
        "maxDurationSeconds": 30,
        "model": {
            "provider": "openai",
            "model": "gpt-4o-mini",
            "messages": [{"role": "system", "content": system_prompt}]
        },
        "firstMessage": "Welcome, please be seated. Shall we begin the interview?",
        "voicemailMessage": "Please call back when you're available.",
        "endCallMessage": "Thank you for your time. Goodbye.",
        "transcriber": {
            "provider": "deepgram",
            "model": "nova-2",
            "language": "en"
        },
        "analysisPlan": {
            "summaryPlan": {"messages": summary_messages},
            "structuredDataPlan": {
                "enabled": True,
                "schema": structured_schema,
                "messages": structured_messages
            },
            "successEvaluationPlan": {
                "rubric": "DescriptiveScale",
                "messages": success_messages
            }
        },
        "metadata": {
            "roll_no": roll_no,
            "app": "drishti-upsc-mock-interview"
        }
    }
    
    response = requests.post(url, headers=headers, json=payload)
    if response.status_code >= 300:
        raise RuntimeError(f"Assistant creation failed: {response.status_code} {response.text}")
    
    return response.json().get("id")

if st.session_state.candidate_json:
    candidate_name = st.session_state.candidate_json.get("name", "Candidate")
    roll_no = st.session_state.candidate_json.get("roll_no", reg_no or "")
    
    # Show current assistant status
    if roll_no in st.session_state.assistants:
        st.success(f"✅ Assistant already created for {candidate_name} (Roll: {roll_no})")
        assistant_info = st.session_state.assistants[roll_no]
        st.info(f"Assistant ID: {assistant_info['assistant_id']}")
    
    if st.button("Create/Update Interview Assistant", type="primary"):
        try:
            with st.spinner("Creating interview assistant..."):
                interview_prompt = create_interview_prompt(st.session_state.candidate_json)
                assistant_name = f"UPSC Board Member - {roll_no}"
                assistant_id = create_vapi_assistant(assistant_name, interview_prompt, roll_no)
                
                st.session_state.assistants[roll_no] = {
                    "assistant_id": assistant_id,
                    "candidate_json": st.session_state.candidate_json,
                    "name": candidate_name
                }
                st.session_state.current_candidate = roll_no
                
            st.success(f"✅ Interview assistant created successfully!")
            st.info(f"Assistant ID: {assistant_id}")
            
        except Exception as e:
            st.error(f"❌ Failed to create assistant: {e}")
else:
    st.info("Please complete Steps 1-2 to create an interview assistant.")

st.markdown("---")

# Step 4: Deploy and Launch Interview
st.header("Step 4: Deploy & Launch Interview")

def deploy_to_github_gist(html_content: str, candidate_name: str, roll_no: str) -> tuple:
    """Deploy HTML to GitHub Gist and return viewable URL"""
    try:
        timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"upsc_interview_{roll_no}_{timestamp}.html"
        
        url = "https://api.github.com/gists"
        headers = {
            "Authorization": f"token {GITHUB_TOKEN}",
            "Accept": "application/vnd.github.v3+json",
            "Content-Type": "application/json"
        }
        
        payload = {
            "description": f"UPSC Mock Interview - {candidate_name} (Roll: {roll_no}) - {dt.datetime.now().strftime('%Y-%m-%d %H:%M')}",
            "public": False,
            "files": {filename: {"content": html_content}}
        }
        
        response = requests.post(url, headers=headers, json=payload)
        
        if response.status_code == 201:
            result = response.json()
            raw_url = result["files"][filename]["raw_url"]
            viewable_url = f"https://htmlpreview.github.io/?{raw_url}"
            return viewable_url, None
        else:
            return None, f"GitHub API Error {response.status_code}: {response.text}"
            
    except Exception as e:
        return None, f"Deployment failed: {str(e)}"

def create_interview_html(candidate_name: str, roll_no: str, assistant_id: str) -> str:
    """Create complete interview HTML with widget integration"""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>UPSC Interview - {candidate_name}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh; color: white; padding: 20px;
        }}
        .container {{ max-width: 1000px; margin: 0 auto; }}
        .header {{ text-align: center; margin-bottom: 30px; }}
        .header h1 {{ font-size: 2.5em; margin-bottom: 10px; text-shadow: 2px 2px 4px rgba(0,0,0,0.3); }}
        .main-panel {{
            background: rgba(255,255,255,0.1); padding: 30px; border-radius: 20px;
            backdrop-filter: blur(15px); border: 1px solid rgba(255,255,255,0.2);
            margin-bottom: 20px;
        }}
        .status-bar {{
            background: rgba(0,0,0,0.4); padding: 15px; border-radius: 10px;
            text-align: center; margin-bottom: 20px; font-weight: 600; font-size: 16px;
        }}
        .info-grid {{ 
            display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); 
            gap: 20px; margin: 20px 0; 
        }}
        .info-card {{
            background: rgba(255,255,255,0.1); padding: 20px; border-radius: 15px;
            backdrop-filter: blur(10px); border: 1px solid rgba(255,255,255,0.2);
        }}
        .info-card h3 {{ color: #fbbf24; margin-bottom: 10px; }}
        .widget-container {{
            background: rgba(255,255,255,0.05); padding: 30px; border-radius: 20px;
            backdrop-filter: blur(10px); border: 1px solid rgba(255,255,255,0.1);
            margin: 30px 0; min-height: 400px; position: relative;
        }}
        .instructions {{
            background: rgba(34, 197, 94, 0.2); border: 2px solid #22c55e;
            padding: 20px; border-radius: 15px; margin: 20px 0;
        }}
        .status-indicator {{
            position: absolute; top: 15px; right: 15px; padding: 8px 15px;
            border-radius: 20px; font-size: 14px; font-weight: 600;
            background: rgba(59, 130, 246, 0.3); color: #3b82f6;
        }}
        @keyframes pulse {{ 0%, 100% {{ opacity: 1; }} 50% {{ opacity: 0.7; }} }}
        .live {{ animation: pulse 1.5s infinite; background: rgba(239, 68, 68, 0.3); color: #ef4444; }}
        @media (max-width: 768px) {{
            .container {{ padding: 15px; }}
            .info-grid {{ grid-template-columns: 1fr; }}
            .header h1 {{ font-size: 2em; }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🎤 UPSC Civil Services Interview</h1>
            <p style="font-size: 1.2em; opacity: 0.9;">Secure HTTPS Interview Platform</p>
        </div>
        
        <div class="status-bar" id="statusBar">
            🔄 Initializing secure interview system...
        </div>
        
        <div class="main-panel">
            <div class="info-grid">
                <div class="info-card">
                    <h3>📋 Interview Details</h3>
                    <p><strong>Candidate:</strong> {candidate_name}</p>
                    <p><strong>Roll Number:</strong> {roll_no}</p>
                    <p><strong>Interview Type:</strong> Personality Test</p>
                    <p><strong>Duration:</strong> 30-35 minutes + feedback</p>
                </div>
                
                <div class="info-card">
                    <h3>🎯 System Status</h3>
                    <p><strong>Security:</strong> <span style="color: #22c55e;">HTTPS Enabled ✓</span></p>
                    <p><strong>Microphone:</strong> <span id="micStatus">Checking...</span></p>
                    <p><strong>Widget:</strong> <span id="widgetStatus">Loading...</span></p>
                    <p><strong>Ready:</strong> <span id="readyStatus">Preparing...</span></p>
                </div>
            </div>
            
            <div class="instructions">
                <h3>📋 Interview Instructions:</h3>
                <ul style="margin-left: 20px; margin-top: 10px;">
                    <li><strong>Microphone:</strong> Allow access when prompted by your browser</li>
                    <li><strong>Environment:</strong> Quiet room with stable internet connection</li>
                    <li><strong>Speaking:</strong> Clear, confident delivery at normal pace</li>
                    <li><strong>Listening:</strong> Pay careful attention to each question</li>
                    <li><strong>Approach:</strong> Be authentic, think before answering, stay calm</li>
                </ul>
            </div>
            
            <div class="widget-container">
                <div class="status-indicator" id="statusIndicator">🔄 Loading</div>
                
                <vapi-widget
                    id="vapiWidget"
                    public-key="{VAPI_PUBLIC_KEY}"
                    assistant-id="{assistant_id}"
                    mode="voice"
                    theme="dark"
                    base-bg-color="rgba(0,0,0,0.2)"
                    accent-color="#14B8A6"
                    cta-button-color="#667eea"
                    cta-button-text-color="#ffffff"
                    border-radius="large"
                    size="full"
                    position="center"
                    title="UPSC MOCK INTERVIEW"
                    start-button-text="🎙️ Begin Interview"
                    end-button-text="📞 End Interview"
                    voice-show-transcript="true"
                    consent-required="true"
                    consent-title="Interview Consent"
                    consent-content="By proceeding, I consent to the recording and analysis of this mock interview session for assessment purposes."
                    consent-storage-key="upsc_interview_consent"
                ></vapi-widget>
            </div>
        </div>
    </div>

    <script src="https://unpkg.com/@vapi-ai/client-sdk-react/dist/embed/widget.umd.js" async></script>
    
    <script>
        let widgetReady = false;
        let interviewActive = false;
        
        function updateStatus(message, type = 'info') {{
            const statusBar = document.getElementById('statusBar');
            const indicator = document.getElementById('statusIndicator');
            const statusEmojis = {{ 'info': '🔄', 'success': '✅', 'warning': '⚠️', 'error': '❌', 'live': '🔴' }};
            
            statusBar.innerHTML = `${{statusEmojis[type] || '🔄'}} ${{message}}`;
            
            if (type === 'live') {{
                indicator.textContent = '🔴 LIVE';
                indicator.classList.add('live');
            }} else {{
                indicator.textContent = type === 'success' ? '✅ Ready' : type === 'error' ? '❌ Error' : '🔄 Loading';
                indicator.classList.remove('live');
            }}
        }}
        
        function updateSystemStatus(component, status, isGood = true) {{
            const element = document.getElementById(component + 'Status');
            if (element) {{
                element.textContent = status;
                element.style.color = isGood ? '#22c55e' : '#ef4444';
                element.style.fontWeight = '600';
            }}
        }}
        
        async function checkMicrophone() {{
            try {{
                updateSystemStatus('mic', 'Testing...', true);
                const stream = await navigator.mediaDevices.getUserMedia({{ audio: true }});
                const tracks = stream.getTracks();
                
                if (tracks.length > 0) {{
                    updateSystemStatus('mic', 'Access granted ✓', true);
                    tracks.forEach(track => track.stop());
                    return true;
                }}
            }} catch (error) {{
                updateSystemStatus('mic', 'Access needed ✗', false);
                updateStatus('⚠️ Please allow microphone access when prompted', 'warning');
                return false;
            }}
        }}
        
        function setupWidget() {{
            const widget = document.getElementById('vapiWidget');
            if (!widget) return;
            
            widget.addEventListener('call-start', () => {{
                interviewActive = true;
                updateStatus('🔴 Interview in progress - Good luck!', 'live');
                updateSystemStatus('ready', 'Live Interview ✓', true);
                document.title = '🔴 LIVE: UPSC Interview - {candidate_name}';
            }});
            
            widget.addEventListener('call-end', () => {{
                interviewActive = false;
                updateStatus('✅ Interview completed successfully', 'success');
                updateSystemStatus('ready', 'Completed ✓', true);
                document.title = '✅ Completed: UPSC Interview - {candidate_name}';
            }});
            
            widget.addEventListener('error', () => {{
                interviewActive = false;
                updateStatus('❌ Technical error - Please refresh and try again', 'error');
                updateSystemStatus('ready', 'Error ✗', false);
            }});
            
            widget.addEventListener('ready', () => {{
                widgetReady = true;
                updateSystemStatus('widget', 'Loaded ✓', true);
                updateSystemStatus('ready', 'Ready to start ✓', true);
                updateStatus('✅ Interview system ready - Click "Begin Interview"', 'success');
            }});
        }}
        
        async function initializeSystem() {{
            updateStatus('🔄 Initializing secure interview system...', 'info');
            
            await checkMicrophone();
            
            setTimeout(() => {{
                setupWidget();
                updateSystemStatus('widget', 'Initializing...', true);
                
                setTimeout(() => {{
                    if (!widgetReady) {{
                        updateStatus('⚠️ Widget loading slowly - please wait', 'warning');
                    }}
                }}, 5000);
            }}, 1000);
        }}
        
        window.addEventListener('beforeunload', (event) => {{
            if (interviewActive) {{
                event.preventDefault();
                event.returnValue = 'Your interview is in progress. Are you sure you want to leave?';
            }}
        }});
        
        document.addEventListener('DOMContentLoaded', initializeSystem);
    </script>
</body>
</html>"""

if st.session_state.assistants and st.session_state.current_candidate:
    current_info = st.session_state.assistants[st.session_state.current_candidate]
    candidate_name = current_info["name"]
    assistant_id = current_info["assistant_id"]
    roll_no = st.session_state.current_candidate
    
    st.success(f"✅ Ready to deploy interview for {candidate_name} (Roll: {roll_no})")
    
    col1, col2 = st.columns(2)
    
    with col1:
        if st.button("🚀 Deploy & Launch Interview", type="primary", use_container_width=True):
            st.session_state.interview_started_at = dt.datetime.now().isoformat()
            st.session_state.interview_status = "starting"
            
            with st.spinner("Deploying to secure HTTPS hosting..."):
                html_content = create_interview_html(candidate_name, roll_no, assistant_id)
                deployed_url, error = deploy_to_github_gist(html_content, candidate_name, roll_no)
                
                if deployed_url:
                    st.session_state.deployed_interview = {
                        'url': deployed_url,
                        'candidate': candidate_name,
                        'roll_no': roll_no,
                        'timestamp': dt.datetime.now()
                    }
                    
                    webbrowser.open(deployed_url)
                    st.success("🚀 Interview deployed successfully!")
                    st.session_state.interview_status = "active"
                else:
                    st.error(f"❌ Deployment failed: {error}")
                    st.session_state.interview_status = "error"
    
    with col2:
        if st.button("💾 Download HTML Backup", use_container_width=True):
            html_content = create_interview_html(candidate_name, roll_no, assistant_id)
            timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M")
            
            st.download_button(
                label="📁 Download Interview File",
                data=html_content,
                file_name=f"upsc_interview_{roll_no}_{timestamp}.html",
                mime="text/html",
                use_container_width=True
            )
    
    # Show deployment status
    if st.session_state.deployed_interview:
        deploy_info = st.session_state.deployed_interview
        
        st.markdown("---")
        st.subheader("📡 Active Deployment")
        
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Status", "🟢 Live & Secure")
        with col2:
            elapsed = dt.datetime.now() - deploy_info['timestamp']
            st.metric("Uptime", f"{elapsed.seconds // 60}m {elapsed.seconds % 60}s")
        with col3:
            st.metric("Security", "HTTPS ✓")
        
        st.code(deploy_info['url'], language=None)
        
        col1, col2, col3 = st.columns(3)
        with col1:
            st.link_button("🔗 Open Interview", deploy_info['url'], use_container_width=True)
        with col2:
            if st.button("📋 Copy URL", use_container_width=True):
                copy_script = f"""
                <script>
                navigator.clipboard.writeText('{deploy_info['url']}').then(() => {{
                    alert('✅ Interview URL copied!');
                }});
                </script>
                """
                st.components.v1.html(copy_script, height=0)
        with col3:
            if st.button("🗑️ Clear", use_container_width=True):
                st.session_state.deployed_interview = None
                st.rerun()

else:
    st.info("Please complete Steps 1-3 to deploy an interview.")

st.markdown("---")

# Step 5: Feedback Analysis
st.header("Step 5: Interview Feedback & Analysis")

def list_calls(assistant_id: str = None) -> List[Dict[str, Any]]:
    """List calls for the assistant"""
    url = f"{VAPI_BASE_URL}/call"
    headers = {"Authorization": f"Bearer {VAPI_API_KEY}"}
    params = {"assistantId": assistant_id, "limit": 50} if assistant_id else {"limit": 50}
    
    response = requests.get(url, headers=headers, params=params)
    if response.status_code >= 300:
        raise RuntimeError(f"List calls failed: {response.status_code}")
    
    data = response.json()
    return data.get("items", []) if isinstance(data, dict) else data

def get_call_details(call_id: str) -> Dict[str, Any]:
    """Get detailed call information"""
    url = f"{VAPI_BASE_URL}/call/{call_id}"
    headers = {"Authorization": f"Bearer {VAPI_API_KEY}"}
    
    response = requests.get(url, headers=headers)
    if response.status_code >= 300:
        raise RuntimeError(f"Get call failed: {response.status_code}")
    
    return response.json()

def format_feedback_table(call_data: Dict[str, Any]) -> pd.DataFrame:
    """Format feedback data for display"""
    analysis = call_data.get("analysis", {})
    structured = analysis.get("structuredData", {})
    
    criteria_mapping = {
        "clarityOfExpression": "Clarity of Expression",
        "reasoningAbility": "Reasoning Ability",
        "analyticalDepth": "Analytical Depth",
        "currentAffairsAwareness": "Current Affairs Awareness",
        "ethicalJudgment": "Ethical Judgment",
        "personalityTraits": "Personality Traits",
        "socialAwareness": "Social Awareness",
        "hobbiesDepth": "Hobbies & Interests",
        "overallImpression": "Overall Impression",
        "strengths": "Key Strengths",
        "areasForImprovement": "Areas for Improvement",
        "overallFeedback": "Overall Feedback"
    }
    
    rows = []
    for key, display_name in criteria_mapping.items():
        if key in structured and structured[key]:
            rows.append({
                "Assessment Criteria": display_name,
                "Detailed Feedback": structured[key]
            })
    
    if not rows:
        rows.append({
            "Assessment Criteria": "Status",
            "Detailed Feedback": "Analysis in progress. Please wait for interview completion."
        })
    
    return pd.DataFrame(rows)

auto_refresh = st.checkbox("Auto-refresh every 10 seconds")
fetch_feedback = st.button("Fetch Latest Feedback", type="primary")

if auto_refresh:
    time.sleep(10)
    st.rerun()

if (fetch_feedback or auto_refresh) and st.session_state.current_candidate:
    assistant_id = st.session_state.assistants[st.session_state.current_candidate]["assistant_id"]
    started_after = st.session_state.interview_started_at or "1970-01-01T00:00:00Z"
    
    try:
        calls = list_calls(assistant_id)
        
        # Filter calls after interview start time
        relevant_calls = []
        for call in calls:
            if call.get("assistantId") == assistant_id:
                call_start = call.get("startedAt", "")
                if call_start >= started_after:
                    relevant_calls.append(call)
        
        if not relevant_calls:
            st.info("⏳ Waiting for interview completion. Feedback will appear automatically.")
        else:
            # Get the most recent call
            latest_call = sorted(relevant_calls, key=lambda x: x.get("endedAt", x.get("updatedAt", "")), reverse=True)[0]
            call_details = get_call_details(latest_call["id"])
            
            analysis = call_details.get("analysis", {})
            summary = analysis.get("summary", "")
            success_eval = analysis.get("successEvaluation", {})
            
            st.subheader("📊 Interview Performance Report")
            st.success("✅ Interview completed and analyzed!")
            
            if summary:
                st.markdown("### 📝 Executive Summary")
                st.info(summary)
                st.markdown("---")
            
            # Detailed feedback
            st.markdown("### 📋 Detailed Assessment")
            feedback_df = format_feedback_table(call_details)
            st.dataframe(feedback_df, use_container_width=True, hide_index=True)
            
            # Overall rating
            if success_eval:
                rating = success_eval.get("overallRating", "")
                justification = success_eval.get("justification", success_eval.get("reason", ""))
                
                if rating:
                    st.markdown("### 🎯 Final Assessment")
                    if rating in ["Highly Suitable", "Suitable"]:
                        st.success(f"🌟 **Overall Assessment: {rating}**")
                    elif rating in ["Borderline"]:
                        st.warning(f"⚖️ **Overall Assessment: {rating}**")
                    elif rating in ["Unsuitable"]:
                        st.error(f"📉 **Overall Assessment: {rating}**")
                    else:
                        st.info(f"📊 **Overall Assessment: {rating}**")
                    
                    if justification:
                        st.markdown(f"**💡 Justification:** {justification}")
            
            # Download options
            st.markdown("---")
            st.markdown("### 📁 Download Resources")
            
            col1, col2, col3 = st.columns(3)
            
            with col1:
                artifact = call_details.get("artifact", {})
                recording = artifact.get("recording", {}).get("mono", {})
                if recording.get("combinedUrl"):
                    st.link_button("🎵 Audio Recording", recording["combinedUrl"], use_container_width=True)
            
            with col2:
                if artifact.get("transcript"):
                    transcript_content = f"""UPSC Mock Interview Transcript
Candidate: {st.session_state.assistants[st.session_state.current_candidate]['name']}
Roll Number: {st.session_state.current_candidate}
Date: {dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

{'-'*50}

{artifact['transcript']}

{'-'*50}
Generated by Drishti UPSC Mock Interview Platform
"""
                    st.download_button(
                        label="📄 Transcript",
                        data=transcript_content,
                        file_name=f"transcript_{st.session_state.current_candidate}_{dt.datetime.now().strftime('%Y%m%d')}.txt",
                        mime="text/plain",
                        use_container_width=True
                    )
            
            with col3:
                # Generate comprehensive report
                report_content = f"""UPSC Mock Interview - Performance Report
Candidate: {st.session_state.assistants[st.session_state.current_candidate]['name']}
Roll Number: {st.session_state.current_candidate}
Interview Date: {dt.datetime.now().strftime('%Y-%m-%d')}

{'-'*60}
EXECUTIVE SUMMARY
{'-'*60}
{summary}

{'-'*60}
OVERALL ASSESSMENT: {rating if 'rating' in locals() else 'Not Available'}
{'-'*60}
{justification if 'justification' in locals() else 'Assessment completed.'}

{'-'*60}
DETAILED PERFORMANCE ANALYSIS
{'-'*60}
"""
                for _, row in feedback_df.iterrows():
                    report_content += f"\n{row['Assessment Criteria']}:\n{row['Detailed Feedback']}\n"
                
                report_content += f"""
{'-'*60}
Report Generated: {dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
Platform: Drishti UPSC Mock Interview System
© Drishti AI Team
"""
                
                st.download_button(
                    label="📊 Full Report",
                    data=report_content,
                    file_name=f"interview_report_{st.session_state.current_candidate}_{dt.datetime.now().strftime('%Y%m%d')}.txt",
                    mime="text/plain",
                    use_container_width=True
                )
            
            # Transcript viewer
            if artifact.get("transcript"):
                with st.expander("📄 View Complete Transcript"):
                    st.text_area("Interview Transcript", artifact["transcript"], height=400)
            
            # Update session status
            st.session_state.interview_status = "completed"
            
    except Exception as e:
        st.error(f"❌ Error fetching feedback: {e}")
        st.session_state.interview_status = "error"

elif not st.session_state.current_candidate:
    st.info("Please complete previous steps to view feedback.")

# Footer
st.markdown("---")
st.markdown("""
<div style="text-align: center; padding: 20px; background: linear-gradient(135deg, #667eea, #764ba2); border-radius: 15px; color: white;">
    <h4>© Drishti AI Team | Secure UPSC Mock Interview Platform</h4>
    <p>🔒 All interviews are encrypted and analyzed securely</p>
    <p>📞 Technical Support: support@drishti.ai</p>
</div>
""", unsafe_allow_html=True)
