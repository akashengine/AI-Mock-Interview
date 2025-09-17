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

# ENHANCED STEP 5 WITH IMPROVED VOICE INTEGRATION
st.markdown("---")
st.header("Step 5 · Start Interview")

# Helper functions for improved functionality
def create_interview_url(vapi_public_key, assistant_id, candidate_name, roll_no, is_mobile=False):
    """Generate a properly formatted interview URL"""
    base_url = "https://cdn.jsdelivr.net/gh/akashengine/ai-mock-interview@main/static/voice.html"
    params = {
        'apiKey': vapi_public_key,
        'assistant': assistant_id,
        'candidate': candidate_name,
        'rollNo': roll_no
    }
    if is_mobile:
        params['mobile'] = 'true'
    
    param_string = '&'.join([f"{k}={v}" for k, v in params.items()])
    return f"{base_url}?{param_string}"

def check_browser_compatibility():
    """Add browser compatibility check"""
    compatibility_script = """
    <script>
    function checkBrowserFeatures() {
        const features = {
            mediaDevices: !!navigator.mediaDevices,
            getUserMedia: !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia),
            webRTC: !!(window.RTCPeerConnection || window.mozRTCPeerConnection || window.webkitRTCPeerConnection),
            popups: true
        };
        
        let warnings = [];
        if (!features.mediaDevices) warnings.push("Media devices not supported");
        if (!features.getUserMedia) warnings.push("Microphone access not available");
        if (!features.webRTC) warnings.push("WebRTC not supported");
        
        if (warnings.length > 0) {
            console.warn("Browser compatibility issues:", warnings);
        }
    }
    checkBrowserFeatures();
    </script>
    """
    return compatibility_script

def add_interview_status_monitoring():
    """Add real-time status monitoring"""
    status_colors = {
        'idle': '⚪ Idle',
        'starting': '🟡 Starting', 
        'active': '🔴 Active',
        'completed': '🟢 Completed',
        'error': '🔴 Error'
    }
    
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Interview Status", status_colors.get(st.session_state.interview_status, '⚪ Unknown'))
    
    with col2:
        if st.session_state.interview_started_at:
            start_time = dt.datetime.fromisoformat(st.session_state.interview_started_at.replace('Z', '+00:00'))
            elapsed = dt.datetime.now(dt.timezone.utc) - start_time
            st.metric("Time Elapsed", str(elapsed).split('.')[0])
        else:
            st.metric("Time Elapsed", "Not started")
    
    with col3:
        if st.button("🔄 Refresh Status", help="Refresh the current status"):
            st.rerun()

def add_interview_instructions():
    """Add comprehensive interview instructions"""
    with st.expander("📋 Complete Interview Guidelines", expanded=False):
        st.markdown("""
        ### 🎯 Before Starting:
        - **Environment**: Ensure you're in a quiet, well-lit room
        - **Technology**: Use Chrome, Firefox, or Safari for best compatibility  
        - **Internet**: Stable broadband connection recommended
        - **Audio**: Test your microphone beforehand
        - **Device**: Desktop/laptop preferred over mobile
        
        ### 🎤 During Interview:
        - **Posture**: Sit upright, maintain good posture
        - **Speech**: Speak clearly, neither too fast nor too slow
        - **Listening**: Listen carefully to each question
        - **Thinking**: Take a moment to think before answering
        - **Length**: Aim for comprehensive but concise answers (2-3 minutes per response)
        
        ### ⚠️ Technical Issues:
        - If audio cuts out, the interviewer will prompt you
        - You can ask for question repetition if needed
        - End the call and restart if major technical issues occur
        - Keep this Streamlit tab open for monitoring
        
        ### 📊 Assessment Areas:
        1. **Clarity of Expression** - How well you communicate your thoughts
        2. **Reasoning Ability** - Your logical thinking and problem-solving process  
        3. **Current Affairs Knowledge** - Awareness of recent developments
        4. **Ethical Judgment** - Your moral reasoning and integrity
        5. **Personality Traits** - Leadership qualities, social awareness, emotional intelligence
        6. **Optional Subject Depth** - Technical knowledge in your chosen subject
        """)

# Add browser compatibility check
st.components.v1.html(check_browser_compatibility(), height=0)

# Add interview instructions
add_interview_instructions()

# Add status monitoring
add_interview_status_monitoring()

if not st.session_state.assistants:
    st.info("⚠️ **Please create an assistant first in Step 4 above.**")
else:
    candidate_keys = list(st.session_state.assistants.keys())
    sel = st.selectbox("Select Candidate", options=candidate_keys, 
                      index=candidate_keys.index(st.session_state.current_candidate) 
                      if st.session_state.current_candidate in candidate_keys else 0)
    st.session_state.current_candidate = sel
    a_id = st.session_state.assistants[sel]["assistant_id"]
    candidate_name = st.session_state.assistants[sel]["name"]

    st.info(f"🎯 **Ready to interview:** {candidate_name} (Roll No: {sel})")
    
    # Main interview launch options
    st.subheader("🚀 Launch Interview")
    
    col1, col2 = st.columns(2)
    
    with col1:
        if st.button("🎙️ **Start Interview (Recommended)**", type="primary", use_container_width=True, help="Opens voice interface in a popup window with full microphone access"):
            st.session_state.interview_started_at = dt.datetime.now(dt.timezone.utc).isoformat()
            st.session_state.interview_status = "starting"
            
            popup_script = f"""
            <script>
            function openVoiceInterview() {{
                const width = 900;
                const height = 700;
                const left = (screen.width - width) / 2;
                const top = (screen.height - height) / 2;
                
                const popup = window.open(
                    'about:blank',
                    'voice_interview_' + Date.now(),
                    `width=${{width}},height=${{height}},left=${{left}},top=${{top}},toolbar=no,menubar=no,scrollbars=yes,resizable=yes`
                );
                
                if (popup) {{
                    popup.document.write(`
                    <!DOCTYPE html>
                    <html>
                    <head>
                        <meta charset="utf-8">
                        <meta name="viewport" content="width=device-width, initial-scale=1">
                        <title>🎤 UPSC Mock Interview - {candidate_name}</title>
                        <style>
                            * {{ margin: 0; padding: 0; box-sizing: border-box; }}
                            body {{ 
                                font-family: 'Segoe UI', system-ui, sans-serif;
                                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                                min-height: 100vh; color: white; padding: 20px;
                            }}
                            .container {{ max-width: 800px; margin: 0 auto; }}
                            .header {{ text-align: center; margin-bottom: 30px; }}
                            .header h1 {{ font-size: 2.2em; margin-bottom: 10px; text-shadow: 2px 2px 4px rgba(0,0,0,0.3); }}
                            .info-card {{ 
                                background: rgba(255,255,255,0.1); padding: 20px; border-radius: 15px; 
                                margin-bottom: 20px; backdrop-filter: blur(10px); border: 1px solid rgba(255,255,255,0.2);
                            }}
                            .widget-container {{ margin-top: 30px; }}
                            .status {{ position: fixed; top: 10px; right: 10px; background: rgba(0,0,0,0.8); padding: 10px; border-radius: 5px; }}
                        </style>
                    </head>
                    <body>
                        <div class="status">🔴 LIVE</div>
                        <div class="container">
                            <div class="header">
                                <h1>🎤 UPSC Civil Services Interview</h1>
                                <p>Personality Test Simulation</p>
                            </div>
                            
                            <div class="info-card">
                                <h3>📋 Candidate Details</h3>
                                <p><strong>Name:</strong> {candidate_name}</p>
                                <p><strong>Roll Number:</strong> {sel}</p>
                                <p><strong>Duration:</strong> 30-35 minutes + 5 min feedback</p>
                                <p><strong>Status:</strong> <span id="callStatus">Ready to start</span></p>
                            </div>
                            
                            <div class="info-card">
                                <h4>🎯 Quick Reminders:</h4>
                                <ul style="margin-left: 20px;">
                                    <li>Allow microphone access when prompted</li>
                                    <li>Speak clearly and at normal pace</li>
                                    <li>Listen carefully to each question</li>
                                    <li>Be confident and authentic</li>
                                </ul>
                            </div>
                            
                            <div class="widget-container">
                                <vapi-widget
                                    public-key="{vapi_public_key}"
                                    assistant-id="{a_id}"
                                    mode="voice"
                                    theme="dark"
                                    base-bg-color="#000000"
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
                                    consent-content="By proceeding, I consent to the recording and analysis of this mock interview session for assessment purposes in accordance with UPSC guidelines."
                                    consent-storage-key="upsc_interview_consent"
                                ></vapi-widget>
                            </div>
                        </div>
                        
                        <script src="https://unpkg.com/@vapi-ai/client-sdk-react/dist/embed/widget.umd.js" async></script>
                        <script>
                            document.addEventListener('DOMContentLoaded', function() {{
                                const widget = document.querySelector('vapi-widget');
                                const statusEl = document.getElementById('callStatus');
                                
                                if (widget) {{
                                    widget.addEventListener('call-start', () => {{
                                        statusEl.textContent = '🔴 Interview in progress';
                                        document.title = '🔴 LIVE: UPSC Interview - {candidate_name}';
                                    }});
                                    
                                    widget.addEventListener('call-end', () => {{
                                        statusEl.textContent = '✅ Interview completed';
                                        document.title = '✅ Completed: UPSC Interview - {candidate_name}';
                                    }});
                                    
                                    widget.addEventListener('error', (e) => {{
                                        statusEl.textContent = '❌ Technical error occurred';
                                        console.error('Widget error:', e);
                                    }});
                                }}
                            }});
                            
                            // Prevent accidental closure
                            window.addEventListener('beforeunload', (e) => {{
                                if (document.title.includes('🔴 LIVE:')) {{
                                    e.preventDefault();
                                    e.returnValue = 'Your interview is in progress. Are you sure you want to leave?';
                                }}
                            }});
                        </script>
                    </body>
                    </html>
                    `);
                    popup.document.close();
                    popup.focus();
                    
                    // Monitor popup
                    const checkClosed = setInterval(() => {{
                        if (popup.closed) {{
                            clearInterval(checkClosed);
                            console.log('Interview window closed');
                        }}
                    }}, 1000);
                    
                }} else {{
                    alert('❌ Popup blocked! Please allow popups for this site and try again.\\n\\nHow to allow popups:\\n1. Click the popup icon in your address bar\\n2. Select "Always allow popups from this site"\\n3. Try again');
                }}
            }}
            openVoiceInterview();
            </script>
            """
            st.components.v1.html(popup_script, height=0)
            st.success("🚀 **Interview window launched!** If you don't see it, please allow popups and try again.")
            st.session_state.interview_status = "active"
    
    with col2:
        external_url = create_interview_url(vapi_public_key, a_id, candidate_name, sel)
        if st.button("🌐 **Open in New Tab**", use_container_width=True, help="Opens the interview in a new browser tab"):
            st.session_state.interview_started_at = dt.datetime.now(dt.timezone.utc).isoformat()
            st.session_state.interview_status = "starting"
            
            # Use JavaScript to open in new tab
            new_tab_script = f"""
            <script>
            window.open('{external_url}', '_blank');
            </script>
            """
            st.components.v1.html(new_tab_script, height=0)
            st.success("🎯 **New tab opened!** Switch to the interview tab to begin.")

    # Additional options
    st.subheader("📱 Alternative Options")
    
    col3, col4 = st.columns(2)
    
    with col3:
        mobile_url = create_interview_url(vapi_public_key, a_id, candidate_name, sel, is_mobile=True)
        st.link_button("📱 Mobile-Friendly Version", mobile_url, use_container_width=True, help="Optimized for mobile devices")
    
    with col4:
        if st.button("📋 Copy Interview Link", use_container_width=True, help="Copy link to share or open manually"):
            copy_script = f"""
            <script>
            navigator.clipboard.writeText('{external_url}').then(() => {{
                alert('✅ Interview link copied to clipboard!');
            }}).catch(() => {{
                prompt('📋 Copy this link manually:', '{external_url}');
            }});
            </script>
            """
            st.components.v1.html(copy_script, height=0)

    # Show current session info
    if st.session_state.interview_started_at:
        start_time = dt.datetime.fromisoformat(st.session_state.interview_started_at.replace('Z', '+00:00'))
        elapsed = dt.datetime.now(dt.timezone.utc) - start_time
        
        st.info(f"""
        ⏱️ **Current Session:**
        - **Started:** {start_time.strftime('%H:%M:%S UTC')}
        - **Elapsed:** {str(elapsed).split('.')[0]}
        - **Status:** {st.session_state.interview_status.title()}
        """)
        
        if st.button("🛑 Reset Session", help="Clear current session and start fresh"):
            st.session_state.interview_started_at = None
            st.session_state.interview_status = "idle"
            st.success("✅ Session reset. You can start a new interview now.")
            st.rerun()

    # Troubleshooting section
    with st.expander("🔧 Troubleshooting", expanded=False):
        st.markdown("""
        ### 🚨 Common Issues & Solutions:
        
        **🎤 Microphone Problems:**
        - Click the 🔒 lock icon in your browser's address bar → Allow microphone
        - Try a different browser (Chrome recommended)
        - Check system microphone settings
        - Restart browser completely
        
        **🌐 Popup Blocked:**
        - Look for popup icon in address bar
        - Select "Always allow popups from this site"
        - Try the "New Tab" option instead
        
        **📞 Call Issues:**
        - Ensure stable internet connection
        - Close other bandwidth-heavy applications
        - Try refreshing and starting again
        - Use wired internet if possible
        
        **📱 Mobile Issues:**
        - Use desktop/laptop for best experience
        - Ensure phone is fully charged
        - Use external microphone/headset if available
        """)

st.markdown("---")
st.header("Step 6 · Fetch & Display Feedback")
auto=st.checkbox("Auto-refresh every 5s", value=False)
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
    for k in order:
        if k in structured and structured[k]: rows.append({"Aspect":k,"Feedback":structured[k]})
    if not rows: rows.append({"Aspect":"Info","Feedback":"No analysis available yet."})
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
                st.info("⏳ No completed interviews found yet. The feedback will appear here once the interview is finished.")
                if st.session_state.interview_status == "active":
                    st.info("🔴 Interview appears to be in progress. Feedback will be generated automatically when completed.")
            else:
                call=fetch_call(vapi_api_key, latest["id"])
                analysis=call.get("analysis") or {}
                summary=analysis.get("summary") or ""
                success=analysis.get("successEvaluation") or {}
                df=flatten_feedback_for_table(call)
                
                st.subheader("📊 Interview Performance Report")
                st.success("✅ Interview completed and analyzed!")
                
                if summary:
                    st.markdown(f"**📝 Interview Summary:**\n{summary}")
                    st.markdown("---")
                
                st.markdown("**📋 Detailed Feedback:**")
                st.table(df)
                
                # Overall rating with color coding
                rating=None; justification=None
                if isinstance(success, dict):
                    rating=success.get("overallRating")
                    justification=success.get("justification") or success.get("reason")
                elif success:
                    rating=str(success)
                
                if rating:
                    if rating in ["Highly Suitable","Suitable"]:
                        st.success(f"🎉 **Overall Assessment: {rating}**")
                    elif rating in ["Borderline"]:
                        st.warning(f"⚠️ **Overall Assessment: {rating}**")
                    elif rating in ["Unsuitable"]:
                        st.error(f"❌ **Overall Assessment: {rating}**")
                    else:
                        st.info(f"📊 **Overall Assessment: {rating}**")
                    
                    if justification:
                        st.markdown(f"**💡 Justification:** {justification}")
                
                # Additional resources
                st.markdown("---")
                col1, col2 = st.columns(2)
                
                with col1:
                    artifact=call.get("artifact") or {}
                    rec=(artifact.get("recording") or {}).get("mono") or {}
                    if rec.get("combinedUrl"): 
                        st.link_button("🎵 Download Recording", rec["combinedUrl"], type="secondary", use_container_width=True)
                
                with col2:
                    if artifact.get("transcript"):
                        with st.expander("📄 View Full Transcript"):
                            st.text_area("Interview Transcript", artifact["transcript"], height=300)
                
                # Update status to completed
                if st.session_state.interview_status in ["starting", "active"]:
                    st.session_state.interview_status = "completed"
                    
        except Exception as e:
            st.error(f"❌ Error fetching feedback: {str(e)}")
            st.session_state.interview_status = "error"

st.markdown("---")
st.caption("© Drishti AI Team | UPSC Mock Interview Platform")
st.caption("🔒 All interviews are recorded and analyzed for assessment purposes only.")
