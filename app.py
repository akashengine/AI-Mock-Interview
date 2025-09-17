import os, json, base64, textwrap, time, datetime as dt
from typing import Any, Dict, List
import streamlit as st, requests, pandas as pd
import threading, functools

APP_TITLE="Drishti UPSC Mock Interview"; APP_SUBTITLE="Developed by Drishti AI Team"
# Load .env if present locally; on Streamlit Cloud, prefer st.secrets
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass
VAPI_BASE_URL="https://api.vapi.ai"
def _get_secret(key:str, default:str="")->str:
    try:
        return st.secrets.get(key, os.getenv(key, default))
    except Exception:
        return os.getenv(key, default)
DEFAULT_VAPI_API_KEY=_get_secret("VAPI_API_KEY","")
DEFAULT_VAPI_PUBLIC_KEY=_get_secret("VAPI_PUBLIC_KEY","")
DEFAULT_GEMINI_API_KEY=_get_secret("GEMINI_API_KEY","")

st.set_page_config(page_title=APP_TITLE, page_icon="🎤", layout="wide")
st.title(APP_TITLE); st.caption(APP_SUBTITLE)

if "candidate_json" not in st.session_state: st.session_state.candidate_json=None
if "rendered_prompt" not in st.session_state: st.session_state.rendered_prompt=None
if "assistants" not in st.session_state: st.session_state.assistants={}
if "current_candidate" not in st.session_state: st.session_state.current_candidate=None
if "interview_started_at" not in st.session_state: st.session_state.interview_started_at=None
if "widget_open" not in st.session_state: st.session_state.widget_open=False
if "interview_status" not in st.session_state: st.session_state.interview_status="idle"

with st.sidebar:
    st.header("Configuration")
    # Hide API key inputs for a clean UI; read from environment insatead
    vapi_api_key=DEFAULT_VAPI_API_KEY
    vapi_public_key=DEFAULT_VAPI_PUBLIC_KEY
    gemini_api_key=DEFAULT_GEMINI_API_KEY
    st.caption("Using Streamlit Secrets / env vars for API keys. Configure in App Settings → Secrets (Cloud) or .env (local).")
    st.divider(); st.subheader("Voice & Model")
    voice_provider=st.selectbox("TTS Provider",["11labs"],index=0)
    voice_id=st.text_input("11labs Voice ID", value="xZp4zaaBzoWhWxxrcAij")
    voice_model=st.text_input("11labs Model", value="eleven_multilingual_v2")
    vapi_llm_model=st.text_input("Assistant LLM (Vapi)", value="gpt-4o-mini")
    transcriber_provider=st.selectbox("STT Provider",["deepgram"],index=0)
    transcriber_model=st.text_input("STT Model", value="nova-2")

st.markdown("---")
st.header("Step 1 · Candidate Inputs")
reg_no=st.text_input("Registration / Roll No.")
daf1_file=st.file_uploader("Upload DAF-1 (PDF/Image)",type=["pdf","png","jpg","jpeg"])
daf2_file=st.file_uploader("Upload DAF-2 (PDF/Image)",type=["pdf","png","jpg","jpeg"])
extract_btn=st.button("Extract Candidate JSON with Gemini", type="primary")

_GEMINI_CLIENT=None
def get_gemini_client(api_key:str):
    global _GEMINI_CLIENT
    if _GEMINI_CLIENT is None:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        _GEMINI_CLIENT=genai
    return _GEMINI_CLIENT

def _mime_for_name(name:str)->str:
    ext=name.split(".")[-1].lower()
    return {"pdf":"application/pdf","jpg":"image/jpeg","jpeg":"image/jpeg","png":"image/png"}.get(ext,"application/octet-stream")

def _safe_json_extract(txt:str)->Dict[str,Any]:
    s=(txt or "").strip()
    if s.startswith("```"): s=s.strip("`")
    i=s.find("{"); j=s.rfind("}")
    if i!=-1 and j!=-1 and j>i: s=s[i:j+1]
    return json.loads(s)

def gemini_extract_candidate_json(api_key:str, files:List[Dict[str,Any]], reg_no:str)->Dict[str,Any]:
    genai=get_gemini_client(api_key)
    model=genai.GenerativeModel("gemini-1.5-flash")
    schema={"name":"string","roll_no":"string","dob":"string","gender":"string","community":"string","religion":"string","mother_tongue":"string","birth_place":"string","home_city":"string","marital_status":"string","employment_status":"string","number_of_attempts":"integer","service_preferences":"array","cadre_preferences":"array","assets":"string","education":"object","optional_subject":"string","language_medium":"string","hobbies":"array","achievements":"array","parents":"object","address":"object","email":"string","phone":"string","work_experience":"array","positions_of_responsibility":"array","extracurriculars":"array","sports":"array","certifications":"array","awards":"array","languages_known":"array","preferred_languages_for_interview":"array","coaching":"string","career_gap_explanations":"string","notable_projects":"array","publications":"array","social_work":"array","disciplinary_actions":"string"}
    sys_prompt=f"You are an expert UPSC DAF parser. Extract a single JSON from DAF-1 and DAF-2 following this schema:\n{json.dumps(schema,indent=2)}\nCandidate roll/registration no.: {reg_no or 'UNKNOWN'}.\nRules:\n- Return valid JSON only.\n- Populate service_preferences and cadre_preferences if present.\n- Capture attempts, employment_status, marital_status, assets.\n- Extract detailed education (10th,12th,graduation,postgrad), work_experience (org, role, duration), positions_of_responsibility, extracurriculars, sports, awards, certifications, languages_known, preferred_languages_for_interview, coaching, career_gap_explanations, notable_projects, publications, social_work, disciplinary_actions.\n- If a field is absent, omit it."
    parts=[{"text":sys_prompt}]
    for f in files:
        b64=base64.b64encode(f["bytes"]).decode()
        parts.append({"inline_data":{"mime_type":f["mime_type"],"data":b64}})
    resp=model.generate_content(parts)
    data=_safe_json_extract(resp.text or "{}")
    if not data.get("roll_no"): data["roll_no"]=reg_no
    return data

if extract_btn:
    if not (daf1_file and daf2_file):
        st.error("Please upload both DAF-1 and DAF-2.")
    elif not gemini_api_key:
        st.error("Gemini API key is missing.")
    else:
        files_for_gemini=[]
        for f in [daf1_file,daf2_file]:
            fb=f.read()
            files_for_gemini.append({"bytes":fb,"mime_type":_mime_for_name(f.name),"filename":f.name})
        try:
            st.session_state.candidate_json=gemini_extract_candidate_json(gemini_api_key,files_for_gemini,reg_no)
            st.success("Extracted candidate JSON with Gemini. Review in Step 2 below.")
        except Exception as e:
            st.error(f"Gemini extraction failed: {e}")

st.markdown("---")
st.header("Step 2 · Review / Edit Candidate JSON")
editable_json_str=st.text_area("Candidate JSON (editable)", value=json.dumps(st.session_state.candidate_json or {}, indent=2, ensure_ascii=False), height=280)
if st.button("Apply Edited JSON"):
    try:
        st.session_state.candidate_json=json.loads(editable_json_str)
        st.success("Candidate JSON updated.")
    except Exception as e:
        st.error(f"Invalid JSON: {e}")

st.markdown("---")
st.header("Step 3 · Review / Edit System Prompt")
FULL_PROMPT_TEMPLATE=textwrap.dedent("""
[Identity]
You are a UPSC Interview Board Member conducting the Civil Services Personality Test.
Role: Senior bureaucrat/academician, neutral and impartial.
Purpose: To simulate a 30–35 minute UPSC Personality Test Interview for candidate {name} (Roll No: {roll_no}), followed by 5 minutes of feedback.

[Style]
- Formal, dignified, polite, and probing.
- Neutral and impartial.
- Adaptive: switch roles between Chair and Subject-Matter Experts.
- Build follow-up questions from candidate's answers.

[Response Guidelines]
- Ask one clear question at a time.
- If vague → ask for specifics.
- If fact-only → seek opinion/analysis.
- If hesitant → reassure.
- If extreme view → present counterview.
- Always stay courteous.

[Task & Flow]
1) Opening (2 min)
2) DAF-based Background (8–10 min)
3) Academic & Optional Subject (8–10 min)
4) Hobbies, ECAs & Personality (5–7 min)
5) Current Affairs & Governance (7–8 min)
6) Closing (2 min)
7) Feedback (5 min)

[Error Handling]
- If candidate says "I don't know" accept gracefully.
- If candidate misunderstands politely clarify.

[Interviewee JSON]
{interviewee_json}
""")
if st.session_state.candidate_json:
    prompt_seed={"name":st.session_state.candidate_json.get("name","Candidate"),"roll_no":st.session_state.candidate_json.get("roll_no",reg_no or ""), "interviewee_json":json.dumps(st.session_state.candidate_json, indent=2, ensure_ascii=False)}
else:
    prompt_seed={"name":"Candidate","roll_no":reg_no or "","interviewee_json":json.dumps({},indent=2)}
st.session_state.rendered_prompt=FULL_PROMPT_TEMPLATE.format(**prompt_seed)
user_prompt=st.text_area("System Prompt (editable)", value=st.session_state.rendered_prompt, height=420)

st.markdown("---")
st.header("Step 4 · Create/Attach Assistant")
cname_default=(st.session_state.candidate_json or {}).get("name") or "Candidate"
create_btn=st.button("Create/Update Assistant For This Candidate", type="primary")

SUMMARY_PLAN_MESSAGES=[{"role":"system","content":"You are an expert note-taker.\nYou will be given a transcript of a call. Summarize the call in 2–3 sentences, highlighting:\n- Key topics/questions asked\n- Candidate's response areas (background, current affairs, ethics, optional subject, hobbies).\n\nOutput: concise, neutral summary (2–3 sentences)."},{"role":"user","content":"Here is the transcript:\n\n{{transcript}}\n\n. Here is the ended reason of the call:\n\n{{endedReason}}\n\n"}]
STRUCTURED_SCHEMA={"type":"object","properties":{"clarityOfExpression":{"type":"string"},"reasoningAbility":{"type":"string"},"analyticalDepth":{"type":"string"},"currentAffairsAwareness":{"type":"string"},"ethicalJudgment":{"type":"string"},"personalityTraits":{"type":"string"},"socialAwareness":{"type":"string"},"hobbiesDepth":{"type":"string"},"overallImpression":{"type":"string"},"strengths":{"type":"string"},"areasForImprovement":{"type":"string"},"overallFeedback":{"type":"string"}}}
STRUCTURED_MESSAGES=[{"role":"system","content":"You are an expert structured-data extractor.\nYou will be given:\n1. The transcript of a call\n2. The system prompt of the AI participant\n\nExtract and structure the following interview performance data. Each field should contain qualitative comments (2–3 sentences max), not numeric scores.\n- clarityOfExpression\n- reasoningAbility\n- analyticalDepth\n- currentAffairsAwareness\n- ethicalJudgment\n- personalityTraits\n- socialAwareness\n- hobbiesDepth\n- overallImpression\nAlso capture overall insights:\n- strengths\n- areasForImprovement\n- overallFeedback\nOutput: JSON with all fields populated.\n\nJson Schema:\n{{schema}}\n\nOnly respond with the JSON."},{"role":"user","content":"Here is the transcript:\n\n{{transcript}}\n\n. Here is the ended reason of the call:\n\n{{endedReason}}\n\n"}]
SUCCESS_PLAN_MESSAGES=[{"role":"system","content":"You are an expert call evaluator.\nYou will be given:\n1. The transcript of a call\n2. The system prompt of the AI participant (UPSC Board Member persona).\nEvaluate the success of the interview based on:\n1. Clarity of Expression\n2. Reasoning & Analytical Depth\n3. Awareness of Current Affairs & Governance\n4. Ethical & Situational Judgment\n5. Personality Traits & Social Awareness\nOverall Success:\n- Highly Suitable\n- Suitable\n- Borderline\n- Unsuitable\nOutput:\n- Overall Success Rating\n- Brief justification (2–3 sentences).\n\nRubric:\n\n{{rubric}}\n\nOnly respond with the evaluation result."},{"role":"user","content":"Here is the transcript of the call:\n\n{{transcript}}\n\n. Here is the ended reason of the call:\n\n{{endedReason}}\n\n"},{"role":"user","content":"Here was the system prompt of the call:\n\n{{systemPrompt}}\n\n"}]

def create_vapi_assistant(api_key:str,name:str,system_prompt:str,voice_provider:str,voice_model:str,voice_id:str,stt_provider:str,stt_model:str,llm_model:str,roll_no_val:str)->str:
    url=f"{VAPI_BASE_URL}/assistant"
    headers={"Authorization":f"Bearer {api_key}","Content-Type":"application/json"}
    payload={"name":name,"voice":{"provider":voice_provider,"model":voice_model,"voiceId":voice_id,"stability":0.5,"similarityBoost":0.75},"model":{"provider":"openai","model":llm_model,"messages":[{"role":"system","content":system_prompt}]},"firstMessage":"Welcome, please be seated. Shall we begin the interview?","voicemailMessage":"Please call back when you're available.","endCallMessage":"Goodbye.","transcriber":{"provider":stt_provider,"model":stt_model,"language":"en"},"analysisPlan":{"summaryPlan":{"messages":SUMMARY_PLAN_MESSAGES},"structuredDataPlan":{"enabled":True,"schema":STRUCTURED_SCHEMA,"messages":STRUCTURED_MESSAGES},"successEvaluationPlan":{"rubric":"DescriptiveScale","messages":SUCCESS_PLAN_MESSAGES}},"metadata":{"roll_no":roll_no_val,"app":"drishti-upsc-mock-interview"}}
    r=requests.post(url,headers=headers,data=json.dumps(payload))
    if r.status_code>=300: raise RuntimeError(f"Assistant create failed: {r.status_code} {r.text}")
    return r.json().get("id")

if create_btn:
    if not vapi_api_key:
        st.error("Vapi API key required.")
    elif not user_prompt.strip():
        st.error("System prompt is empty.")
    else:
        try:
            rn=(st.session_state.candidate_json or {}).get("roll_no") or reg_no or "NA"
            assistant_name=f"UPSC BOARD MEMBER – {rn}"
            a_id=create_vapi_assistant(vapi_api_key,assistant_name,user_prompt,voice_provider,voice_model,voice_id,transcriber_provider,transcriber_model,vapi_llm_model,rn)
            st.session_state.assistants[rn]={"assistant_id":a_id,"candidate_json":st.session_state.candidate_json or {},"name":(st.session_state.candidate_json or {}).get("name",cname_default)}
            st.session_state.current_candidate=rn
            st.success(f"Assistant created for {rn}: {a_id}")
        except Exception as e:
            st.error(str(e))

# REPLACE YOUR STEP 5 WITH THIS FINAL SOLUTION

import streamlit as st
import tempfile
import webbrowser
import os
import datetime as dt

st.markdown("---")
st.header("Step 5 · Start Interview (Direct SDK Integration)")

def create_direct_vapi_html(vapi_public_key, assistant_id, candidate_name, roll_no):
    """Create HTML file with direct Vapi Web SDK integration"""
    return f"""
<!DOCTYPE html>
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
        .header h1 {{ 
            font-size: 2.5em; margin-bottom: 10px; text-shadow: 2px 2px 4px rgba(0,0,0,0.3);
            background: linear-gradient(45deg, #fff, #e0e7ff);
            -webkit-background-clip: text; -webkit-text-fill-color: transparent;
        }}
        .main-panel {{
            background: rgba(255,255,255,0.1); padding: 30px; border-radius: 20px;
            backdrop-filter: blur(15px); border: 1px solid rgba(255,255,255,0.2);
            margin-bottom: 20px;
        }}
        .status-bar {{
            background: rgba(0,0,0,0.4); padding: 15px; border-radius: 10px;
            text-align: center; margin-bottom: 20px; font-weight: 600; font-size: 16px;
        }}
        .controls {{ 
            display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px; margin: 20px 0;
        }}
        .btn {{
            padding: 15px 20px; border: none; border-radius: 12px; font-size: 16px;
            font-weight: 600; cursor: pointer; transition: all 0.3s ease;
            display: flex; align-items: center; justify-content: center; gap: 8px;
        }}
        .btn-primary {{ background: #14b8a6; color: white; }}
        .btn-danger {{ background: #ef4444; color: white; }}
        .btn-secondary {{ background: rgba(255,255,255,0.2); color: white; }}
        .btn:hover {{ transform: translateY(-2px); box-shadow: 0 8px 25px rgba(0,0,0,0.3); }}
        .btn:disabled {{ 
            opacity: 0.5; cursor: not-allowed; transform: none; 
            background: rgba(107, 114, 128, 0.5);
        }}
        .info-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 20px; margin: 20px 0; }}
        .info-card {{
            background: rgba(255,255,255,0.1); padding: 20px; border-radius: 15px;
            backdrop-filter: blur(10px); border: 1px solid rgba(255,255,255,0.2);
        }}
        .info-card h3 {{ color: #fbbf24; margin-bottom: 10px; }}
        .transcript-panel {{
            background: rgba(0,0,0,0.4); padding: 20px; border-radius: 15px;
            margin-top: 20px; max-height: 400px; overflow-y: auto;
            display: none;
        }}
        .transcript-entry {{
            margin-bottom: 15px; padding: 10px; background: rgba(255,255,255,0.1);
            border-radius: 8px; border-left: 4px solid #14b8a6;
        }}
        .speaker {{ font-weight: 600; color: #14b8a6; margin-bottom: 5px; }}
        .timestamp {{ font-size: 12px; color: rgba(255,255,255,0.7); }}
        .error-panel {{ 
            background: rgba(239, 68, 68, 0.2); border: 2px solid #ef4444;
            padding: 20px; border-radius: 15px; margin: 20px 0; text-align: center;
        }}
        .success-panel {{ 
            background: rgba(34, 197, 94, 0.2); border: 2px solid #22c55e;
            padding: 20px; border-radius: 15px; margin: 20px 0; text-align: center;
        }}
        .warning-panel {{ 
            background: rgba(251, 191, 36, 0.2); border: 2px solid #f59e0b;
            padding: 20px; border-radius: 15px; margin: 20px 0; text-align: center;
        }}
        @keyframes pulse {{ 0%, 100% {{ opacity: 1; }} 50% {{ opacity: 0.7; }} }}
        .pulse {{ animation: pulse 2s infinite; }}
        @media (max-width: 768px) {{
            .container {{ padding: 15px; }}
            .controls {{ grid-template-columns: 1fr; }}
            .info-grid {{ grid-template-columns: 1fr; }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🎤 UPSC Civil Services Interview</h1>
            <p style="font-size: 1.2em; opacity: 0.9;">Direct Voice Integration System</p>
        </div>
        
        <div class="status-bar" id="statusBar">
            🔄 Initializing advanced voice system...
        </div>
        
        <div class="main-panel">
            <div class="info-grid">
                <div class="info-card">
                    <h3>📋 Candidate Information</h3>
                    <p><strong>Name:</strong> {candidate_name}</p>
                    <p><strong>Roll Number:</strong> {roll_no}</p>
                    <p><strong>Interview Type:</strong> Personality Test</p>
                    <p><strong>Duration:</strong> 30-35 minutes</p>
                </div>
                
                <div class="info-card">
                    <h3>🎯 System Status</h3>
                    <p><strong>Voice SDK:</strong> <span id="sdkStatus">Loading...</span></p>
                    <p><strong>Microphone:</strong> <span id="micStatus">Checking...</span></p>
                    <p><strong>Connection:</strong> <span id="connectionStatus">Connecting...</span></p>
                    <p><strong>Interview:</strong> <span id="interviewStatus">Ready</span></p>
                </div>
            </div>
            
            <div class="controls">
                <button class="btn btn-primary" id="startBtn" onclick="startInterview()" disabled>
                    🎙️ Start Interview
                </button>
                <button class="btn btn-danger" id="endBtn" onclick="endInterview()" disabled>
                    📞 End Interview
                </button>
                <button class="btn btn-secondary" id="muteBtn" onclick="toggleMute()" disabled>
                    🔇 Toggle Mute
                </button>
                <button class="btn btn-secondary" id="transcriptBtn" onclick="toggleTranscript()" disabled>
                    📄 Show Transcript
                </button>
            </div>
        </div>
        
        <div class="transcript-panel" id="transcriptPanel">
            <h3>📝 Live Interview Transcript</h3>
            <div id="transcriptContent"></div>
        </div>
    </div>

    <!-- Load Vapi Web SDK -->
    <script src="https://unpkg.com/@vapi-ai/web@latest/dist/index.js"></script>
    
    <script>
        // Global variables
        let vapi = null;
        let isCallActive = false;
        let isMuted = false;
        let transcriptVisible = false;
        let interviewStartTime = null;
        
        // Status update function
        function updateStatus(message, type = 'info') {{
            const statusBar = document.getElementById('statusBar');
            const statusEmojis = {{
                'info': '🔄',
                'success': '✅', 
                'warning': '⚠️',
                'error': '❌',
                'live': '🔴'
            }};
            
            statusBar.innerHTML = `${{statusEmojis[type] || '🔄'}} ${{message}}`;
            statusBar.className = 'status-bar';
            
            if (type === 'live') {{
                statusBar.classList.add('pulse');
            }} else {{
                statusBar.classList.remove('pulse');
            }}
        }}
        
        function updateSystemStatus(component, status, isGood = true) {{
            const element = document.getElementById(component + 'Status');
            if (element) {{
                element.textContent = status;
                element.style.color = isGood ? '#22c55e' : '#ef4444';
            }}
        }}
        
        function updateButtons() {{
            const startBtn = document.getElementById('startBtn');
            const endBtn = document.getElementById('endBtn');
            const muteBtn = document.getElementById('muteBtn');
            const transcriptBtn = document.getElementById('transcriptBtn');
            
            if (isCallActive) {{
                startBtn.disabled = true;
                endBtn.disabled = false;
                muteBtn.disabled = false;
                transcriptBtn.disabled = false;
                muteBtn.innerHTML = isMuted ? '🎤 Unmute' : '🔇 Mute';
            }} else {{
                startBtn.disabled = false;
                endBtn.disabled = true;
                muteBtn.disabled = true;
                transcriptBtn.disabled = true;
            }}
        }}
        
        function showPanel(type, message) {{
            // Remove existing panels
            const existingPanels = document.querySelectorAll('.error-panel, .success-panel, .warning-panel');
            existingPanels.forEach(panel => panel.remove());
            
            const panel = document.createElement('div');
            panel.className = type + '-panel';
            panel.innerHTML = message;
            
            const mainPanel = document.querySelector('.main-panel');
            mainPanel.parentNode.insertBefore(panel, mainPanel.nextSibling);
            
            // Auto-remove success panels after 5 seconds
            if (type === 'success') {{
                setTimeout(() => {{
                    if (panel.parentNode) panel.remove();
                }}, 5000);
            }}
        }}
        
        async function checkMicrophone() {{
            try {{
                updateSystemStatus('mic', 'Testing...', true);
                
                const stream = await navigator.mediaDevices.getUserMedia({{ audio: true }});
                const tracks = stream.getTracks();
                
                if (tracks.length > 0) {{
                    console.log('Microphone access granted:', tracks[0].label || 'Default microphone');
                    updateSystemStatus('mic', 'Access granted ✓', true);
                    
                    // Stop the test stream
                    tracks.forEach(track => track.stop());
                    return true;
                }}
            }} catch (error) {{
                console.error('Microphone access failed:', error);
                updateSystemStatus('mic', 'Access denied ✗', false);
                
                let errorMessage = 'Microphone access was denied. ';
                if (error.name === 'NotAllowedError') {{
                    errorMessage += 'Please allow microphone access and refresh the page.';
                }} else if (error.name === 'NotFoundError') {{
                    errorMessage += 'No microphone found. Please connect a microphone.';
                }} else {{
                    errorMessage += 'Please check your microphone settings.';
                }}
                
                showPanel('error', `
                    <h3>🎤 Microphone Access Required</h3>
                    <p>${{errorMessage}}</p>
                    <button onclick="location.reload()" style="margin-top: 15px; padding: 10px 20px; background: #ef4444; color: white; border: none; border-radius: 8px; cursor: pointer;">
                        🔄 Retry
                    </button>
                `);
                
                return false;
            }}
        }}
        
        async function initializeVapi() {{
            try {{
                updateStatus('Loading Vapi Web SDK...', 'info');
                updateSystemStatus('sdk', 'Loading...', true);
                
                // Check if Vapi is available
                if (typeof window.Vapi === 'undefined') {{
                    throw new Error('Vapi SDK not loaded. Please check your internet connection.');
                }}
                
                // Initialize Vapi client
                vapi = new window.Vapi('{vapi_public_key}');
                updateSystemStatus('sdk', 'Loaded ✓', true);
                
                // Set up event listeners
                vapi.on('call-start', () => {{
                    console.log('📞 Call started');
                    isCallActive = true;
                    interviewStartTime = new Date();
                    updateStatus('🔴 Interview in progress', 'live');
                    updateSystemStatus('interview', 'Live Interview', true);
                    updateButtons();
                    showPanel('success', '🎉 Interview started successfully! Speak clearly and confidently.');
                    document.title = '🔴 LIVE: UPSC Interview - {candidate_name}';
                }});
                
                vapi.on('call-end', () => {{
                    console.log('📞 Call ended');
                    isCallActive = false;
                    const duration = interviewStartTime ? 
                        Math.round((new Date() - interviewStartTime) / 1000 / 60) : 0;
                    updateStatus('✅ Interview completed', 'success');
                    updateSystemStatus('interview', `Completed (${{duration}} min)`, true);
                    updateButtons();
                    showPanel('success', `
                        🎉 Interview completed successfully!<br>
                        Duration: ${{duration}} minutes<br>
                        Your performance is being analyzed.
                    `);
                    document.title = '✅ Completed: UPSC Interview - {candidate_name}';
                }});
                
                vapi.on('speech-start', () => {{
                    updateStatus('🎤 Listening to candidate...', 'info');
                }});
                
                vapi.on('speech-end', () => {{
                    updateStatus('🔴 Interview in progress', 'live');
                }});
                
                vapi.on('message', (message) => {{
                    console.log('📝 Message received:', message);
                    
                    if (message.type === 'transcript' && message.transcript) {{
                        addTranscriptEntry(message.role, message.transcript);
                    }}
                    
                    if (message.type === 'function-call') {{
                        console.log('🔧 Function call:', message.functionCall);
                    }}
                }});
                
                vapi.on('error', (error) => {{
                    console.error('❌ Vapi error:', error);
                    isCallActive = false;
                    updateStatus('❌ Interview system error', 'error');
                    updateSystemStatus('interview', 'Error', false);
                    updateButtons();
                    
                    showPanel('error', `
                        <h3>❌ Interview System Error</h3>
                        <p>Error: ${{error.message || 'Unknown error occurred'}}</p>
                        <p>Please refresh the page and try again.</p>
                        <button onclick="location.reload()" style="margin-top: 15px; padding: 10px 20px; background: #ef4444; color: white; border: none; border-radius: 8px; cursor: pointer;">
                            🔄 Refresh Page
                        </button>
                    `);
                }});
                
                vapi.on('call-connecting', () => {{
                    updateStatus('🔄 Connecting to interview board...', 'info');
                    updateSystemStatus('interview', 'Connecting...', true);
                }});
                
                updateSystemStatus('connection', 'Connected ✓', true);
                updateStatus('✅ Voice system ready - Click "Start Interview"', 'success');
                updateButtons();
                
                showPanel('success', `
                    <h3>🎯 System Ready!</h3>
                    <p>All systems are operational. Click "Start Interview" to begin your UPSC Personality Test.</p>
                    <p><strong>Remember:</strong> Speak clearly, listen carefully, and be confident!</p>
                `);
                
            }} catch (error) {{
                console.error('Failed to initialize Vapi:', error);
                updateSystemStatus('sdk', 'Failed ✗', false);
                updateSystemStatus('connection', 'Failed ✗', false);
                updateStatus('❌ Failed to initialize voice system', 'error');
                
                showPanel('error', `
                    <h3>❌ System Initialization Failed</h3>
                    <p>${{error.message}}</p>
                    <p>Please check your internet connection and try again.</p>
                    <button onclick="location.reload()" style="margin-top: 15px; padding: 10px 20px; background: #ef4444; color: white; border: none; border-radius: 8px; cursor: pointer;">
                        🔄 Retry Initialization
                    </button>
                `);
            }}
        }}
        
        async function startInterview() {{
            try {{
                if (!vapi) {{
                    throw new Error('Voice system not initialized');
                }}
                
                updateStatus('🔄 Starting interview session...', 'info');
                updateSystemStatus('interview', 'Starting...', true);
                
                // Start the call with the assistant
                await vapi.start('{assistant_id}');
                
            }} catch (error) {{
                console.error('Failed to start interview:', error);
                updateStatus('❌ Failed to start interview', 'error');
                updateSystemStatus('interview', 'Failed to start', false);
                
                showPanel('error', `
                    <h3>❌ Failed to Start Interview</h3>
                    <p>${{error.message}}</p>
                    <p>Please try again or refresh the page.</p>
                `);
            }}
        }}
        
        async function endInterview() {{
            try {{
                if (!vapi || !isCallActive) {{
                    return;
                }}
                
                updateStatus('🔄 Ending interview session...', 'info');
                vapi.stop();
                
            }} catch (error) {{
                console.error('Failed to end interview:', error);
                showPanel('error', `
                    <h3>❌ Failed to End Interview</h3>
                    <p>${{error.message}}</p>
                `);
            }}
        }}
        
        async function toggleMute() {{
            try {{
                if (!vapi || !isCallActive) return;
                
                if (isMuted) {{
                    vapi.setMuted(false);
                    isMuted = false;
                    updateStatus('🎤 Microphone unmuted', 'info');
                }} else {{
                    vapi.setMuted(true);
                    isMuted = true;
                    updateStatus('🔇 Microphone muted', 'warning');
                }}
                
                updateButtons();
                
            }} catch (error) {{
                console.error('Failed to toggle mute:', error);
            }}
        }}
        
        function toggleTranscript() {{
            const panel = document.getElementById('transcriptPanel');
            const btn = document.getElementById('transcriptBtn');
            
            if (transcriptVisible) {{
                panel.style.display = 'none';
                btn.innerHTML = '📄 Show Transcript';
                transcriptVisible = false;
            }} else {{
                panel.style.display = 'block';
                btn.innerHTML = '📄 Hide Transcript';
                transcriptVisible = true;
            }}
        }}
        
        function addTranscriptEntry(role, transcript) {{
            const transcriptContent = document.getElementById('transcriptContent');
            const entry = document.createElement('div');
            entry.className = 'transcript-entry';
            
            const timestamp = new Date().toLocaleTimeString();
            entry.innerHTML = `
                <div class="speaker">${{role.toUpperCase()}}:</div>
                <div>${{transcript}}</div>
                <div class="timestamp">${{timestamp}}</div>
            `;
            
            transcriptContent.appendChild(entry);
            transcriptContent.scrollTop = transcriptContent.scrollHeight;
        }}
        
        // Page lifecycle management
        window.addEventListener('beforeunload', (event) => {{
            if (isCallActive) {{
                event.preventDefault();
                event.returnValue = 'Your UPSC interview is in progress. Are you sure you want to leave?';
                return event.returnValue;
            }}
        }});
        
        document.addEventListener('visibilitychange', () => {{
            if (document.hidden && isCallActive) {{
                updateStatus('⚠️ Interview paused - window not visible', 'warning');
            }} else if (!document.hidden && isCallActive) {{
                updateStatus('🔴 Interview resumed', 'live');
            }}
        }});
        
        // Initialize everything when page loads
        document.addEventListener('DOMContentLoaded', async () => {{
            console.log('🚀 UPSC Interview System starting...');
            
            // Step 1: Check microphone access
            const micOk = await checkMicrophone();
            
            // Step 2: Initialize Vapi (even if mic failed, user might fix it)
            setTimeout(async () => {{
                await initializeVapi();
            }}, 1000);
            
            console.log('✅ System initialization completed');
        }});
    </script>
</body>
</html>
    """

def add_streamlit_direct_sdk_interface():
    """Add the direct SDK interface to Streamlit"""
    
    if not st.session_state.assistants:
        st.error("⚠️ Please create an assistant first in Step 4 above.")
        return
    
    # Candidate selection
    candidate_keys = list(st.session_state.assistants.keys())
    sel = st.selectbox("Select Candidate", options=candidate_keys,
                      index=candidate_keys.index(st.session_state.current_candidate) 
                      if st.session_state.current_candidate in candidate_keys else 0)
    
    st.session_state.current_candidate = sel
    a_id = st.session_state.assistants[sel]["assistant_id"]
    candidate_name = st.session_state.assistants[sel]["name"]
    
    # Status display
    status_colors = {"idle": "🔵", "starting": "🟡", "active": "🔴", "completed": "🟢"}
    st.info(f"{status_colors.get(st.session_state.interview_status, '🔵')} **Status:** {st.session_state.interview_status.title()} | **Candidate:** {candidate_name} (Roll: {sel})")
    
    # Main launch options
    st.subheader("🚀 Direct Voice Integration (No Popup Issues)")
    
    col1, col2 = st.columns(2)
    
    with col1:
        if st.button("🎙️ **Launch Interview (Recommended)**", type="primary", use_container_width=True, 
                    help="Opens full-screen interview with direct microphone access"):
            st.session_state.interview_started_at = dt.datetime.now(dt.timezone.utc).isoformat()
            st.session_state.interview_status = "starting"
            
            # Create HTML content
            html_content = create_direct_vapi_html(vapi_public_key, a_id, candidate_name, sel)
            
            # Save to temporary file and open in browser
            try:
                with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False) as f:
                    f.write(html_content)
                    temp_file = f.name
                
                # Open in default browser
                webbrowser.open('file://' + temp_file)
                st.success("🚀 **Interview launched successfully!** Check your browser for the interview window.")
                st.info("💡 **Tip:** The interview opens in a new browser window with full microphone access - no popup blocking issues!")
                
                # Clean up the temp file after a delay (optional)
                import threading
                def cleanup():
                    import time
                    time.sleep(300)  # Wait 5 minutes
                    try:
                        os.unlink(temp_file)
                    except:
                        pass
                threading.Thread(target=cleanup, daemon=True).start()
                
            except Exception as e:
                st.error(f"❌ Failed to launch interview: {str(e)}")
                st.session_state.interview_status = "error"
    
    with col2:
        # Alternative: Save and download HTML file
        if st.button("💾 **Download Interview File**", use_container_width=True,
                    help="Download HTML file to open manually"):
            html_content = create_direct_vapi_html(vapi_public_key, a_id, candidate_name, sel)
            
            st.download_button(
                label="📁 Download Interview.html",
                data=html_content,
                file_name=f"upsc_interview_{sel}_{dt.datetime.now().strftime('%Y%m%d_%H%M')}.html",
                mime="text/html",
                use_container_width=True
            )
            st.info("💡 **Instructions:** Download the file and open it in your browser for the interview.")

    # Embedded version (may have limitations)
    with st.expander("📱 Alternative: Embedded Version (Limited)", expanded=False):
        st.warning("⚠️ **Note:** This embedded version may have microphone limitations. Use the main launch button above for best results.")
        
        if st.button("🔗 Try Embedded Version"):
            embedded_html = f"""
            <div style="height: 600px; background: linear-gradient(135deg, #667eea, #764ba2); border-radius: 15px; padding: 20px; color: white;">
                <script src="https://unpkg.com/@vapi-ai/web@latest/dist/index.js"></script>
                <div style="text-align: center;">
                    <h3>🎤 UPSC Interview - Embedded Mode</h3>
                    <p>Candidate: {candidate_name} | Roll: {sel}</p>
                    <div style="margin: 20px 0;">
                        <button id="embedStart" style="background: #14b8a6; color: white; border: none; padding: 15px 25px; border-radius: 10px; font-size: 16px; font-weight: 600; cursor: pointer; margin: 5px;">
                            🎙️ Start Interview
                        </button>
                        <button id="embedEnd" style="background: #ef4444; color: white; border: none; padding: 15px 25px; border-radius: 10px; font-size: 16px; font-weight: 600; cursor: pointer; margin: 5px;" disabled>
                            📞 End Interview
                        </button>
                    </div>
                    <div id="embedStatus" style="padding: 15px; background: rgba(0,0,0,0.3); border-radius: 10px; margin: 10px 0;">
                        Initializing...
                    </div>
                </div>
                
                <script>
                let embedVapi = null;
                let embedActive = false;
                
                document.addEventListener('DOMContentLoaded', function() {{
                    if (typeof window.Vapi !== 'undefined') {{
                        embedVapi = new window.Vapi('{vapi_public_key}');
                        
                        embedVapi.on('call-start', () => {{
                            embedActive = true;
                            document.getElementById('embedStatus').innerHTML = '🔴 Interview in progress';
                            document.getElementById('embedStart').disabled = true;
                            document.getElementById('embedEnd').disabled = false;
                        }});
                        
                        embedVapi.on('call-end', () => {{
                            embedActive = false;
                            document.getElementById('embedStatus').innerHTML = '✅ Interview completed';
                            document.getElementById('embedStart').disabled = false;
                            document.getElementById('embedEnd').disabled = true;
                        }});
                        
                        embedVapi.on('error', (error) => {{
                            document.getElementById('embedStatus').innerHTML = '❌ Error: ' + error.message;
                            embedActive = false;
                            document.getElementById('embedStart').disabled = false;
                            document.getElementById('embedEnd').disabled = true;
                        }});
                        
                        document.getElementById('embedStart').onclick = () => {{
                            embedVapi.start('{a_id}');
                        }};
                        
                        document.getElementById('embedEnd').onclick = () => {{
                            embedVapi.stop();
                        }};
                        
                        document.getElementById('embedStatus').innerHTML = '✅ Ready to start (⚠️ May have microphone limitations)';
                    }} else {{
                        document.getElementById('embedStatus').innerHTML = '❌ SDK not loaded - try the main launch button above';
                    }}
                }});
                </script>
            </div>
            """
            st.components.v1.html(embedded_html, height=600)

    # Session management
    if st.session_state.interview_started_at:
        start_time = dt.datetime.fromisoformat(st.session_state.interview_started_at.replace('Z', '+00:00'))
        elapsed = dt.datetime.now(dt.timezone.utc) - start_time
        
        st.info(f"""
        ⏱️ **Active Session:**
        - **Started:** {start_time.strftime('%H:%M:%S UTC')}
        - **Elapsed:** {str(elapsed).split('.')[0]}
        - **Status:** {st.session_state.interview_status.title()}
        """)
        
        if st.button("🔄 Reset Session"):
            st.session_state.interview_started_at = None
            st.session_state.interview_status = "idle"
            st.success("✅ Session reset successfully.")
            st.rerun()

    # Instructions and help
    with st.expander("📋 How This Works & Troubleshooting", expanded=False):
        st.markdown("""
        ### 🎯 **How Direct SDK Integration Works:**
        
        **✅ Advantages:**
        - **No popup blocking** - Opens directly in browser
        - **Full microphone access** - No iframe restrictions  
        - **Professional interface** - Clean, modern design
        - **Real-time feedback** - Live status updates and transcript
        - **Reliable performance** - Direct API integration
        
        ### 🚀 **Usage Instructions:**
        
        1. **Click "Launch Interview"** - Opens in new browser window/tab
        2. **Allow microphone access** when prompted by browser
        3. **Click "Start Interview"** in the interview window
        4. **Conduct your interview** - Speak clearly and confidently
        5. **Click "End Interview"** when finished
        6. **Return to Streamlit** for feedback analysis
        
        ### 🔧 **Troubleshooting:**
        
        **If interview window doesn't open:**
        - Check if popup/tab blockers are enabled
        - Try the "Download Interview File" option
        - Manually open the downloaded HTML file in browser
        
        **If microphone doesn't work:**
        - Allow microphone access when browser prompts
        - Check browser microphone settings
        - Try different browser (Chrome recommended)
        - Ensure no other apps are using microphone
        
        **If connection fails:**
        - Check internet connection
        - Refresh the interview window
        - Try again in a few minutes
        - Contact support if issue persists
        
        ### 🎤 **Best Practices:**
        - Use desktop/laptop for best experience
        - Use external microphone or headset
        - Ensure stable internet connection
        - Close unnecessary browser tabs
        - Test microphone before starting
        """)

# Add the interface to your app
add_streamlit_direct_sdk_interface()

st.markdown("---")
st.markdown("""
<div style="text-align: center; padding: 20px; background: linear-gradient(135deg, #667eea, #764ba2); border-radius: 15px; color: white;">
    <h4>© Drishti AI Team | UPSC Mock Interview Platform</h4>
    <p>🔒 All interviews are recorded and analyzed for assessment purposes only.</p>
    <p>📞 For technical support: <strong>support@drishti.ai</strong></p>
</div>
""", unsafe_allow_html=True)
