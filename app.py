import os, json, base64, textwrap, time, datetime as dt
from typing import Any, Dict, List
import streamlit as st, requests, pandas as pd
import threading, functools
import tempfile
import webbrowser

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
if "interview_status" not in st.session_state: st.session_state.interview_status="idle"

with st.sidebar:
    st.header("Configuration")
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

# FINAL STEP 5: WIDGET SCRIPT INTEGRATION (FIXED SOLUTION)
st.markdown("---")
st.header("Step 5 · Start Interview (Widget Script Integration)")

def create_widget_based_interview(vapi_public_key, assistant_id, candidate_name, roll_no):
    """Create HTML file using reliable Vapi widget script"""
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
        .widget-title {{
            text-align: center; margin-bottom: 20px; font-size: 1.3em;
            color: #14b8a6; font-weight: 600;
        }}
        .instructions {{
            background: rgba(34, 197, 94, 0.2); border: 2px solid #22c55e;
            padding: 20px; border-radius: 15px; margin: 20px 0;
        }}
        .warning {{
            background: rgba(251, 191, 36, 0.2); border: 2px solid #f59e0b;
            padding: 20px; border-radius: 15px; margin: 20px 0;
        }}
        .status-indicator {{
            position: absolute; top: 15px; right: 15px; padding: 8px 15px;
            border-radius: 20px; font-size: 14px; font-weight: 600;
        }}
        .status-ready {{ background: rgba(34, 197, 94, 0.3); color: #22c55e; }}
        .status-loading {{ background: rgba(59, 130, 246, 0.3); color: #3b82f6; }}
        .status-error {{ background: rgba(239, 68, 68, 0.3); color: #ef4444; }}
        .status-live {{ background: rgba(239, 68, 68, 0.3); color: #ef4444; animation: pulse 1.5s infinite; }}
        @keyframes pulse {{ 0%, 100% {{ opacity: 1; }} 50% {{ opacity: 0.7; }} }}
        
        /* Vapi widget customization */
        vapi-widget {{
            --primary-color: #14b8a6;
            --secondary-color: #667eea;
            --text-color: white;
            --background-color: rgba(0,0,0,0.3);
            --border-radius: 15px;
        }}
        
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
            <p style="font-size: 1.2em; opacity: 0.9;">Widget-Based Voice Integration</p>
        </div>
        
        <div class="status-bar" id="statusBar">
            🔄 Initializing interview system...
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
                    <h3>🎯 System Information</h3>
                    <p><strong>Integration:</strong> Vapi Widget Script</p>
                    <p><strong>Microphone:</strong> <span id="micStatus">Checking...</span></p>
                    <p><strong>Widget Status:</strong> <span id="widgetStatus">Loading...</span></p>
                    <p><strong>Ready Status:</strong> <span id="readyStatus">Preparing...</span></p>
                </div>
            </div>
            
            <div class="instructions">
                <h3>📋 Before You Begin:</h3>
                <ul style="margin-left: 20px; margin-top: 10px;">
                    <li><strong>Microphone:</strong> Allow microphone access when prompted</li>
                    <li><strong>Environment:</strong> Ensure quiet surroundings</li>
                    <li><strong>Speaking:</strong> Speak clearly and at normal pace</li>
                    <li><strong>Listening:</strong> Pay careful attention to questions</li>
                    <li><strong>Confidence:</strong> Be authentic and confident in your responses</li>
                </ul>
            </div>
            
            <div class="widget-container">
                <div class="status-indicator status-loading" id="statusIndicator">
                    🔄 Loading
                </div>
                <div class="widget-title">Voice Interview Interface</div>
                
                <!-- Vapi Widget Integration -->
                <vapi-widget
                    id="vapiWidget"
                    public-key="{vapi_public_key}"
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
                    consent-content="By proceeding, I consent to the recording and analysis of this mock interview session for assessment purposes as per UPSC Civil Services guidelines. I understand that this is a practice session designed to help improve my interview performance."
                    consent-storage-key="upsc_interview_consent"
                ></vapi-widget>
            </div>
        </div>
        
        <div class="warning" id="troubleshootingSection" style="display: none;">
            <h3>🔧 Troubleshooting Help</h3>
            <p>If you're experiencing issues:</p>
            <ul style="margin-left: 20px; margin-top: 10px;">
                <li>Refresh this page and try again</li>
                <li>Check your internet connection</li>
                <li>Allow microphone access when prompted</li>
                <li>Try a different browser (Chrome recommended)</li>
                <li>Disable ad blockers temporarily</li>
            </ul>
            <button onclick="location.reload()" style="margin-top: 15px; padding: 10px 20px; background: #f59e0b; color: white; border: none; border-radius: 8px; cursor: pointer; font-weight: 600;">
                🔄 Refresh Page
            </button>
        </div>
    </div>

    <!-- Load Vapi Widget Script -->
    <script src="https://unpkg.com/@vapi-ai/client-sdk-react/dist/embed/widget.umd.js" async></script>
    
    <script>
        let widgetLoaded = false;
        let interviewActive = false;
        let microphoneAccess = false;
        let interviewStartTime = null;
        
        // Status update functions
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
            
            // Update status indicator
            const indicator = document.getElementById('statusIndicator');
            indicator.className = 'status-indicator status-' + (type === 'live' ? 'live' : type === 'error' ? 'error' : type === 'success' ? 'ready' : 'loading');
            indicator.textContent = type === 'live' ? '🔴 LIVE' : type === 'error' ? '❌ Error' : type === 'success' ? '✅ Ready' : '🔄 Loading';
        }}
        
        function updateSystemStatus(component, status, isGood = true) {{
            const element = document.getElementById(component + 'Status');
            if (element) {{
                element.textContent = status;
                element.style.color = isGood ? '#22c55e' : '#ef4444';
                element.style.fontWeight = '600';
            }}
        }}
        
        function showTroubleshooting() {{
            document.getElementById('troubleshootingSection').style.display = 'block';
        }}
        
        // Check microphone access
        async function checkMicrophone() {{
            try {{
                updateSystemStatus('mic', 'Testing...', true);
                
                const stream = await navigator.mediaDevices.getUserMedia({{ audio: true }});
                const tracks = stream.getTracks();
                
                if (tracks.length > 0) {{
                    microphoneAccess = true;
                    updateSystemStatus('mic', 'Access granted ✓', true);
                    console.log('✅ Microphone access granted:', tracks[0].label || 'Default');
                    
                    // Stop test stream
                    tracks.forEach(track => track.stop());
                    return true;
                }}
            }} catch (error) {{
                console.error('❌ Microphone access failed:', error);
                microphoneAccess = false;
                updateSystemStatus('mic', 'Access denied ✗', false);
                
                // Show specific error guidance
                let errorMsg = 'Please allow microphone access when prompted by your browser.';
                if (error.name === 'NotFoundError') {{
                    errorMsg = 'No microphone detected. Please connect a microphone.';
                }} else if (error.name === 'NotAllowedError') {{
                    errorMsg = 'Microphone access denied. Please refresh and allow access.';
                }}
                
                updateStatus('⚠️ ' + errorMsg, 'warning');
                return false;
            }}
        }}
        
        // Widget event handling
        function setupWidgetEvents() {{
            const widget = document.getElementById('vapiWidget');
            
            if (!widget) {{
                console.error('Widget element not found');
                return;
            }}
            
            // Widget event listeners
            widget.addEventListener('call-start', () => {{
                console.log('📞 Interview started');
                interviewActive = true;
                interviewStartTime = new Date();
                updateStatus('🔴 Interview in progress - Speak clearly and confidently', 'live');
                updateSystemStatus('ready', 'Interview Active', true);
                document.title = '🔴 LIVE: UPSC Interview - {candidate_name}';
            }});
            
            widget.addEventListener('call-end', () => {{
                console.log('📞 Interview ended');
                interviewActive = false;
                const duration = interviewStartTime ? 
                    Math.round((new Date() - interviewStartTime) / 1000 / 60) : 0;
                updateStatus(`✅ Interview completed successfully (${{duration}} minutes)`, 'success');
                updateSystemStatus('ready', 'Completed', true);
                document.title = '✅ Completed: UPSC Interview - {candidate_name}';
            }});
            
            widget.addEventListener('error', (event) => {{
                console.error('❌ Widget error:', event);
                interviewActive = false;
                updateStatus('❌ Interview error occurred', 'error');
                updateSystemStatus('ready', 'Error', false);
                showTroubleshooting();
            }});
            
            widget.addEventListener('loading', () => {{
                console.log('🔄 Widget loading...');
                updateStatus('🔄 Preparing interview session...', 'info');
            }});
            
            widget.addEventListener('ready', () => {{
                console.log('✅ Widget ready');
                widgetLoaded = true;
                updateSystemStatus('widget', 'Loaded ✓', true);
                updateSystemStatus('ready', 'Ready to start', true);
                updateStatus('✅ Interview system ready - Click "Begin Interview" to start', 'success');
            }});
            
            // Additional events for better UX
            widget.addEventListener('call-connecting', () => {{
                updateStatus('🔄 Connecting to interview board...', 'info');
            }});
            
            widget.addEventListener('speech-start', () => {{
                console.log('🎤 User speaking...');
            }});
            
            widget.addEventListener('speech-end', () => {{
                console.log('🎤 User finished speaking');
            }});
        }}
        
        // Check if widget script is loaded
        function checkWidgetScript() {{
            let checkCount = 0;
            const maxChecks = 30; // 15 seconds total
            
            const checkInterval = setInterval(() => {{
                checkCount++;
                
                if (typeof window.VapiWidget !== 'undefined' || document.querySelector('vapi-widget')) {{
                    clearInterval(checkInterval);
                    updateSystemStatus('widget', 'Script loaded ✓', true);
                    setupWidgetEvents();
                    
                    // Give widget a moment to initialize
                    setTimeout(() => {{
                        if (!widgetLoaded) {{
                            updateSystemStatus('widget', 'Initializing...', true);
                        }}
                    }}, 2000);
                    
                }} else if (checkCount >= maxChecks) {{
                    clearInterval(checkInterval);
                    updateSystemStatus('widget', 'Failed to load ✗', false);
                    updateStatus('❌ Widget script failed to load', 'error');
                    showTroubleshooting();
                }}
            }}, 500);
        }}
        
        // Initialize everything
        async function initializeSystem() {{
            console.log('🚀 Initializing UPSC Interview System...');
            
            updateStatus('🔄 Starting system initialization...', 'info');
            updateSystemStatus('widget', 'Loading script...', true);
            
            // Step 1: Check microphone
            await checkMicrophone();
            
            // Step 2: Check widget script loading
            checkWidgetScript();
            
            console.log('📋 System initialization completed');
        }}
        
        // Page lifecycle management
        window.addEventListener('beforeunload', (event) => {{
            if (interviewActive) {{
                event.preventDefault();
                event.returnValue = 'Your UPSC interview is currently in progress. Leaving will end the session. Are you sure?';
                return event.returnValue;
            }}
        }});
        
        document.addEventListener('visibilitychange', () => {{
            if (document.hidden && interviewActive) {{
                console.log('⚠️ Interview window hidden');
            }} else if (!document.hidden && interviewActive) {{
                console.log('✅ Interview window visible again');
            }}
        }});
        
        // Start initialization when DOM is ready
        document.addEventListener('DOMContentLoaded', () => {{
            console.log('📄 DOM loaded, starting initialization...');
            initializeSystem();
        }});
        
        // Fallback initialization after 3 seconds
        setTimeout(() => {{
            if (!widgetLoaded && !interviewActive) {{
                console.log('🔄 Fallback initialization triggered');
                initializeSystem();
            }}
        }}, 3000);
    </script>
</body>
</html>
    """

if not st.session_state.assistants:
    st.error("⚠️ Please create an assistant first in Step 4 above.")
else:
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
    
    # Main interface
    st.subheader("🎙️ Widget-Based Voice Integration (FIXED)")
    st.success("✅ **Using reliable Vapi widget script instead of Web SDK**")
    
    col1, col2 = st.columns(2)
    
    with col1:
        if st.button("🚀 **Launch Interview (Widget)**", type="primary", use_container_width=True, 
                    help="Opens interview with reliable widget script integration"):
            st.session_state.interview_started_at = dt.datetime.now(dt.timezone.utc).isoformat()
            st.session_state.interview_status = "starting"
            
            try:
                # Create HTML with widget script
                html_content = create_widget_based_interview(vapi_public_key, a_id, candidate_name, sel)
                
                # Save and open
                with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False) as f:
                    f.write(html_content)
                    temp_file = f.name
                
                webbrowser.open('file://' + temp_file)
                st.success("🚀 **Widget-based interview launched!** This approach is more reliable than Web SDK.")
                st.info("💡 **Key Advantages:** No SDK loading issues, direct widget integration, better compatibility.")
                
                # Cleanup after delay
                import threading
                def cleanup():
                    import time
                    time.sleep(300)
                    try:
                        os.unlink(temp_file)
                    except:
                        pass
                threading.Thread(target=cleanup, daemon=True).start()
                
            except Exception as e:
                st.error(f"❌ Failed to launch: {str(e)}")
                st.session_state.interview_status = "error"
    
    with col2:
        if st.button("💾 **Download Widget Version**", use_container_width=True,
                    help="Download HTML file to open manually"):
            html_content = create_widget_based_interview(vapi_public_key, a_id, candidate_name, sel)
            
            st.download_button(
                label="📁 Download Interview-Widget.html",
                data=html_content,
                file_name=f"upsc_interview_widget_{sel}_{dt.datetime.now().strftime('%Y%m%d_%H%M')}.html",
                mime="text/html",
                use_container_width=True
            )

    # Session management
    if st.session_state.interview_started_at:
        start_time = dt.datetime.fromisoformat(st.session_state.interview_started_at.replace('Z', '+00:00'))
        elapsed = dt.datetime.now(dt.timezone.utc) - start_time
        
        st.info(f"""
        ⏱️ **Active Session:**
        - **Started:** {start_time.strftime('%H:%M:%S UTC')}
        - **Elapsed:** {str(elapsed).split('.')[0]}
        - **Method:** Widget Script Integration
        """)
        
        if st.button("🔄 Reset Session"):
            st.session_state.interview_started_at = None
            st.session_state.interview_status = "idle"
            st.success("✅ Session reset.")
            st.rerun()

st.markdown("---")
st.header("Step 6 · Fetch & Display Feedback")
auto=st.checkbox("Auto-refresh every 5s", value=False, help="Automatically check for interview completion")
fetch_now=st.button("Fetch Latest Feedback For Selected Candidate", type="primary")

if auto:
    time.sleep(5)
    st.rerun()

def list_calls(api_key:str, params:Dict[str,Any]=None)->List[Dict[str,Any]]:
    url=f"{VAPI_BASE_URL}/call"
    headers={"Authorization":f"Bearer {api_key}"}
    r=requests.get(url,headers=headers,params=params or {})
    if r.status_code>=300: raise RuntimeError(f"List Calls failed: {r.status_code} {r.text}")
    data=r.json()
    if isinstance(data,dict) and "items" in data: return data["items"]
    if isinstance(data,list): return data
    return []

def get_latest_call_for_assistant(api_key:str, assistant_id:str, started_after_iso:str)->Dict[str,Any]:
    items=[]
    try:
        items=list_calls(api_key, params={"assistantId":assistant_id,"limit":50})
    except Exception:
        items=list_calls(api_key, params={"limit":50})
    def after_start(c):
        try:
            return c.get("startedAt") and c["startedAt"]>=started_after_iso
        except Exception:
            return True
    filtered=[c for c in items if c.get("assistantId")==assistant_id and after_start(c)]
    filtered=sorted(filtered, key=lambda x: x.get("endedAt") or x.get("updatedAt") or x.get("createdAt") or "", reverse=True)
    return filtered[0] if filtered else {}

def fetch_call(api_key:str, call_id:str)->Dict[str,Any]:
    url=f"{VAPI_BASE_URL}/call/{call_id}"
    headers={"Authorization":f"Bearer {api_key}"}
    r=requests.get(url,headers=headers)
    if r.status_code>=300: raise RuntimeError(f"Get Call failed: {r.status_code} {r.text}")
    return r.json()

def flatten_feedback_for_table(call_obj:Dict[str,Any])->pd.DataFrame:
    analysis=call_obj.get("analysis") or {}
    structured=analysis.get("structuredData") or {}
    rows=[]
    order=["clarityOfExpression","reasoningAbility","analyticalDepth","currentAffairsAwareness","ethicalJudgment","personalityTraits","socialAwareness","hobbiesDepth","overallImpression","strengths","areasForImprovement","overallFeedback"]
    display_names={"clarityOfExpression":"Clarity of Expression","reasoningAbility":"Reasoning Ability","analyticalDepth":"Analytical Depth","currentAffairsAwareness":"Current Affairs Awareness","ethicalJudgment":"Ethical Judgment","personalityTraits":"Personality Traits","socialAwareness":"Social Awareness","hobbiesDepth":"Hobbies & Interests","overallImpression":"Overall Impression","strengths":"Key Strengths","areasForImprovement":"Areas for Improvement","overallFeedback":"Overall Feedback"}
    for k in order:
        if k in structured and structured[k]: 
            rows.append({"Assessment Criteria":display_names.get(k,k),"Detailed Feedback":structured[k]})
    if not rows: rows.append({"Assessment Criteria":"Status","Detailed Feedback":"Analysis in progress. Please wait for interview completion."})
    return pd.DataFrame(rows)

if fetch_now or auto:
    if not vapi_api_key:
        st.error("Vapi API key required.")
    elif not st.session_state.current_candidate:
        st.error("Select a candidate.")
    else:
        a_id=st.session_state.assistants[st.session_state.current_candidate]["assistant_id"]
        started_after=st.session_state.interview_started_at or "1970-01-01T00:00:00Z"
        try:
            latest=get_latest_call_for_assistant(vapi_api_key,a_id,started_after)
            if not latest:
                st.info("⏳ **Waiting for interview completion...** Feedback will appear automatically once the interview is finished and analyzed.")
                if st.session_state.interview_status == "active":
                    st.info("🔴 **Interview in progress.** Keep this tab open to monitor completion status.")
            else:
                call=fetch_call(vapi_api_key, latest["id"])
                analysis=call.get("analysis") or {}
                summary=analysis.get("summary") or ""
                success=analysis.get("successEvaluation") or {}
                df=flatten_feedback_for_table(call)
                
                st.subheader("📊 Comprehensive Interview Performance Report")
                st.success("✅ **Interview completed and comprehensive analysis generated!**")
                
                # Interview summary
                if summary:
                    st.markdown("### 📝 Executive Summary")
                    st.info(summary)
                    st.markdown("---")
                
                # Detailed feedback table
                st.markdown("### 📋 Detailed Performance Assessment")
                st.dataframe(df, use_container_width=True, hide_index=True)
                
                # Overall rating with enhanced presentation
                rating=None; justification=None
                if isinstance(success, dict):
                    rating=success.get("overallRating")
                    justification=success.get("justification") or success.get("reason")
                elif success:
                    rating=str(success)
                
                if rating:
                    st.markdown("### 🎯 Final Assessment")
                    if rating in ["Highly Suitable","Suitable"]:
                        st.success(f"🌟 **Overall Assessment: {rating}**")
                    elif rating in ["Borderline"]:
                        st.warning(f"⚖️ **Overall Assessment: {rating}**")
                    elif rating in ["Unsuitable"]:
                        st.error(f"📉 **Overall Assessment: {rating}**")
                    else:
                        st.info(f"📊 **Overall Assessment: {rating}**")
                    
                    if justification:
                        st.markdown(f"**💡 Assessment Rationale:** {justification}")
                
                # Additional resources
                st.markdown("---")
                st.markdown("### 📁 Interview Resources")
                
                col1, col2, col3 = st.columns(3)
                
                with col1:
                    artifact=call.get("artifact") or {}
                    rec=(artifact.get("recording") or {}).get("mono") or {}
                    if rec.get("combinedUrl"): 
                        st.link_button("🎵 Download Audio Recording", rec["combinedUrl"], type="secondary", use_container_width=True)
                
                with col2:
                    if artifact.get("transcript"):
                        transcript_content = f"""UPSC Mock Interview Transcript
Candidate: {candidate_name}
Roll Number: {sel}
Date: {dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

{'-'*50}

{artifact['transcript']}

{'-'*50}
Generated by Drishti UPSC Mock Interview System
"""
                        st.download_button(
                            label="📄 Download Transcript",
                            data=transcript_content,
                            file_name=f"interview_transcript_{sel}_{dt.datetime.now().strftime('%Y%m%d')}.txt",
                            mime="text/plain",
                            use_container_width=True
                        )
                
                with col3:
                    structured_data = analysis.get("structuredData") or {}
                    feedback_content = f"""UPSC Mock Interview - Performance Report
Candidate: {candidate_name}
Roll Number: {sel}
Interview Date: {dt.datetime.now().strftime('%Y-%m-%d')}
Assessment System: Drishti AI

{'-'*50}
EXECUTIVE SUMMARY
{'-'*50}
{summary}

{'-'*50}
OVERALL ASSESSMENT: {rating or 'Not Available'}
{'-'*50}
{justification or 'Detailed assessment completed.'}

{'-'*50}
DETAILED PERFORMANCE ANALYSIS
{'-'*50}
"""
                    for _, row in df.iterrows():
                        feedback_content += f"\n{row['Assessment Criteria']}:\n{row['Detailed Feedback']}\n"
                    
                    feedback_content += f"""
{'-'*50}
Report generated on: {dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
System: Drishti UPSC Mock Interview Platform
© Drishti AI Team
"""
                    
                    st.download_button(
                        label="📊 Download Report",
                        data=feedback_content,
                        file_name=f"interview_report_{sel}_{dt.datetime.now().strftime('%Y%m%d')}.txt",
                        mime="text/plain",
                        use_container_width=True
                    )
                
                # Transcript viewer
                if artifact.get("transcript"):
                    with st.expander("📄 View Complete Interview Transcript", expanded=False):
                        st.text_area("Full Interview Transcript", artifact["transcript"], height=400, help="Complete conversation record")
                
                # Update status to completed
                if st.session_state.interview_status in ["starting", "active"]:
                    st.session_state.interview_status = "completed"
                    
        except Exception as e:
            st.error(f"❌ **Error fetching feedback:** {str(e)}")
            st.session_state.interview_status = "error"

st.markdown("---")
st.markdown("""
<div style="text-align: center; padding: 20px; background: linear-gradient(135deg, #667eea, #764ba2); border-radius: 15px; color: white;">
    <h4>© Drishti AI Team | UPSC Mock Interview Platform</h4>
    <p>🔒 All interviews are recorded and analyzed for assessment purposes only.</p>
    <p>📞 For technical support: <strong>support@drishti.ai</strong></p>
    <p><em>Widget Script Integration - Reliable Voice Interview Solution</em></p>
</div>
""", unsafe_allow_html=True)
