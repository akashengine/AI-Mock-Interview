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

# FINAL ENHANCED STEP 5 WITH ALL FIXES
st.markdown("---")
st.header("Step 5 · Start Interview")

# Helper functions
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

def show_popup_instructions():
    """Browser-specific popup instructions"""
    with st.expander("🚫 Popup Blocked? Click here for help", expanded=False):
        tab1, tab2, tab3, tab4 = st.tabs(["Chrome", "Firefox", "Safari", "Edge"])
        
        with tab1:
            st.markdown("""
            **Chrome Instructions:**
            1. Look for 🚫 icon in address bar (right side)
            2. Click it → Select "Always allow popups and redirects"
            3. Refresh page and try interview button again
            
            **Alternative:** Right-click interview button → "Open link in new tab"
            """)
            
        with tab2:
            st.markdown("""
            **Firefox Instructions:**
            1. Look for 🛡️ shield icon in address bar
            2. Click it → Turn off "Blocking Pop-up Windows"
            3. Refresh page and try interview button again
            """)
            
        with tab3:
            st.markdown("""
            **Safari Instructions:**
            1. Safari menu → Preferences → Websites
            2. Click "Pop-up Windows" → Find your site
            3. Change to "Allow" → Try again
            """)
            
        with tab4:
            st.markdown("""
            **Edge Instructions:**
            1. Look for 🚫 icon in address bar
            2. Click it → "Always allow popups from this site"
            3. Refresh and try again
            """)

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

def add_mobile_detection():
    """Mobile detection and guidance"""
    mobile_script = """
    <script>
    if (/Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent)) {
        document.getElementById('mobile-warning').style.display = 'block';
    }
    </script>
    
    <div id="mobile-warning" style="display: none; background: linear-gradient(135deg, #f59e0b, #d97706); color: white; padding: 15px; border-radius: 10px; margin: 15px 0;">
        <strong>📱 Mobile Device Detected</strong><br>
        For the best interview experience, we recommend using a desktop or laptop computer.
        Mobile devices may have limited microphone functionality.
    </div>
    """
    return mobile_script

# Add mobile detection
st.components.v1.html(add_mobile_detection(), height=80)

# Add instructions
add_interview_instructions()
show_popup_instructions()

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

    # Status display
    status_colors = {"idle": "🔵 Ready", "starting": "🟡 Starting", "active": "🔴 Active", "completed": "🟢 Completed", "error": "🔴 Error"}
    st.info(f"🎯 **Interview Status:** {status_colors.get(st.session_state.interview_status, '🔵 Ready')} | **Candidate:** {candidate_name} (Roll No: {sel})")
    
    # Main interview launch section
    st.subheader("🚀 Launch Interview")
    
    # Primary launch buttons
    col1, col2 = st.columns(2)
    
    with col1:
        if st.button("🎙️ **Start Interview (Best Quality)**", type="primary", use_container_width=True, help="Opens optimized popup window with full microphone access"):
            st.session_state.interview_started_at = dt.datetime.now(dt.timezone.utc).isoformat()
            st.session_state.interview_status = "starting"
            
            # Enhanced popup script with smart detection and fallback
            popup_script = f"""
            <script>
            function smartInterviewLaunch() {{
                // Test popup capability first
                const testPopup = window.open('', '_test', 'width=1,height=1');
                
                if (testPopup && !testPopup.closed) {{
                    // Popups work - close test popup and open interview
                    testPopup.close();
                    openEnhancedPopup();
                }} else {{
                    // Popup blocked - show instruction and fallback
                    if (testPopup) testPopup.close();
                    showPopupBlockedDialog();
                }}
            }}
            
            function openEnhancedPopup() {{
                const width = 950;
                const height = 750;
                const left = Math.max(0, (screen.width - width) / 2);
                const top = Math.max(0, (screen.height - height) / 2);
                
                const popup = window.open(
                    'about:blank',
                    'upsc_interview_' + Date.now(),
                    `width=${{width}},height=${{height}},left=${{left}},top=${{top}},toolbar=no,menubar=no,scrollbars=yes,resizable=yes,status=no`
                );
                
                if (popup) {{
                    popup.document.write(`
                    <!DOCTYPE html>
                    <html lang="en">
                    <head>
                        <meta charset="utf-8">
                        <meta name="viewport" content="width=device-width, initial-scale=1">
                        <title>🎤 UPSC Mock Interview - {candidate_name}</title>
                        <link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>🎤</text></svg>">
                        <style>
                            * {{ margin: 0; padding: 0; box-sizing: border-box; }}
                            body {{ 
                                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                                min-height: 100vh; color: white; padding: 20px;
                                display: flex; flex-direction: column;
                            }}
                            .status-bar {{ 
                                position: fixed; top: 0; left: 0; right: 0; 
                                background: linear-gradient(90deg, #000, #1a1a1a); color: #4ade80; 
                                padding: 10px 20px; text-align: center; z-index: 1000;
                                font-weight: 600; font-size: 14px; letter-spacing: 0.5px;
                                border-bottom: 2px solid #14b8a6; box-shadow: 0 2px 10px rgba(0,0,0,0.3);
                            }}
                            .container {{ max-width: 900px; margin: 50px auto 0; flex: 1; }}
                            .header {{ text-align: center; margin-bottom: 25px; }}
                            .header h1 {{ 
                                font-size: 2.4em; margin-bottom: 5px; 
                                text-shadow: 2px 2px 4px rgba(0,0,0,0.3);
                                background: linear-gradient(45deg, #fff, #e0e7ff);
                                -webkit-background-clip: text; -webkit-text-fill-color: transparent;
                                background-clip: text; font-weight: 700;
                            }}
                            .info-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 25px; }}
                            .info-card {{ 
                                background: rgba(255,255,255,0.1); padding: 20px; border-radius: 15px; 
                                backdrop-filter: blur(15px); border: 1px solid rgba(255,255,255,0.2);
                                box-shadow: 0 8px 32px rgba(0,0,0,0.1); transition: transform 0.2s ease;
                            }}
                            .info-card:hover {{ transform: translateY(-2px); }}
                            .info-card h3 {{ margin-bottom: 12px; color: #fbbf24; font-size: 1.1em; }}
                            .info-card p {{ margin: 6px 0; font-size: 0.95em; }}
                            .info-card ul {{ margin-left: 18px; margin-top: 10px; }}
                            .info-card li {{ margin: 5px 0; font-size: 0.9em; }}
                            .widget-container {{ 
                                margin-top: 25px; background: rgba(255,255,255,0.05); 
                                border-radius: 20px; padding: 25px; backdrop-filter: blur(10px);
                                border: 1px solid rgba(255,255,255,0.1);
                            }}
                            .loading {{ 
                                text-align: center; padding: 40px;
                                background: rgba(255,255,255,0.1); border-radius: 15px;
                                backdrop-filter: blur(10px);
                            }}
                            .loading h3 {{ color: #60a5fa; margin-bottom: 15px; font-size: 1.3em; }}
                            .error-box, .success-box {{
                                border-radius: 12px; padding: 20px; margin: 20px 0; text-align: center;
                                font-weight: 500; backdrop-filter: blur(10px);
                            }}
                            .error-box {{ background: rgba(239, 68, 68, 0.2); border: 2px solid #ef4444; }}
                            .success-box {{ background: rgba(34, 197, 94, 0.2); border: 2px solid #22c55e; }}
                            @keyframes pulse {{ 0%, 100% {{ opacity: 1; }} 50% {{ opacity: 0.7; }} }}
                            .pulse {{ animation: pulse 2s infinite; }}
                            @media (max-width: 768px) {{
                                .info-grid {{ grid-template-columns: 1fr; }}
                                .container {{ margin: 50px 15px 0; }}
                                .header h1 {{ font-size: 2em; }}
                            }}
                        </style>
                    </head>
                    <body>
                        <div class="status-bar" id="statusBar">
                            🔄 Initializing Advanced Interview System...
                        </div>
                        
                        <div class="container">
                            <div class="header">
                                <h1>🎤 UPSC Civil Services Interview</h1>
                                <p style="opacity: 0.9; font-size: 1.1em;">Personality Test Simulation</p>
                            </div>
                            
                            <div class="info-grid">
                                <div class="info-card">
                                    <h3>📋 Interview Details</h3>
                                    <p><strong>Candidate:</strong> {candidate_name}</p>
                                    <p><strong>Roll Number:</strong> {sel}</p>
                                    <p><strong>Duration:</strong> 30-35 minutes + feedback</p>
                                    <p><strong>Status:</strong> <span id="sessionStatus">Preparing...</span></p>
                                </div>
                                
                                <div class="info-card">
                                    <h3>🎯 Quick Reminders</h3>
                                    <ul style="font-size: 0.9em;">
                                        <li>Allow microphone access when prompted</li>
                                        <li>Speak clearly and confidently</li>
                                        <li>Listen carefully to each question</li>
                                        <li>Take a moment to think before answering</li>
                                    </ul>
                                </div>
                            </div>
                            
                            <div class="widget-container" id="widgetContainer">
                                <div class="loading pulse" id="loadingMessage">
                                    <h3>🔄 Loading Advanced Voice Interface...</h3>
                                    <p>Preparing microphone access and AI interview system</p>
                                    <p style="margin-top: 10px; font-size: 0.9em; opacity: 0.8;">This may take a few moments...</p>
                                </div>
                            </div>
                        </div>
                        
                        <script>
                            // Enhanced status management
                            function updateStatus(message, type = 'info') {{
                                const statusBar = document.getElementById('statusBar');
                                const statusEmoji = {{
                                    'info': '🔄', 'success': '✅', 'warning': '⚠️', 'error': '❌', 'live': '🔴'
                                }};
                                statusBar.innerHTML = `${{statusEmoji[type] || '🔄'}} ${{message}}`;
                                statusBar.style.background = {{
                                    'success': 'linear-gradient(90deg, #059669, #065f46)',
                                    'warning': 'linear-gradient(90deg, #d97706, #92400e)', 
                                    'error': 'linear-gradient(90deg, #dc2626, #991b1b)',
                                    'live': 'linear-gradient(90deg, #dc2626, #991b1b)'
                                }}[type] || 'linear-gradient(90deg, #000, #1a1a1a)';
                            }}
                            
                            function updateSessionStatus(status) {{
                                document.getElementById('sessionStatus').textContent = status;
                            }}
                            
                            function showError(message, canRetry = true) {{
                                const container = document.getElementById('widgetContainer');
                                container.innerHTML = `
                                    <div class="error-box">
                                        <h3>❌ Technical Issue Detected</h3>
                                        <p>${{message}}</p>
                                        ${{canRetry ? '<button onclick="location.reload()" style="margin-top: 15px; padding: 12px 24px; background: #ef4444; color: white; border: none; border-radius: 8px; cursor: pointer; font-weight: 600; font-size: 14px;">🔄 Retry Interview Setup</button>' : ''}}
                                    </div>
                                `;
                                updateStatus('Technical error - please retry', 'error');
                            }}
                            
                            function showSuccess(message) {{
                                const container = document.getElementById('widgetContainer');
                                const successDiv = document.createElement('div');
                                successDiv.className = 'success-box';
                                successDiv.innerHTML = `<p>${{message}}</p>`;
                                container.insertBefore(successDiv, container.firstChild);
                                setTimeout(() => {{ if (successDiv.parentNode) successDiv.remove(); }}, 5000);
                            }}
                            
                            // Enhanced microphone permission check
                            async function checkMicrophonePermission() {{
                                try {{
                                    updateStatus('Verifying microphone access...', 'info');
                                    updateSessionStatus('Checking microphone');
                                    
                                    const stream = await navigator.mediaDevices.getUserMedia({{ audio: true }});
                                    const audioTracks = stream.getAudioTracks();
                                    
                                    if (audioTracks.length > 0) {{
                                        console.log('Microphone detected:', audioTracks[0].label);
                                        updateStatus('Microphone access confirmed', 'success');
                                        updateSessionStatus('Microphone ready ✓');
                                    }}
                                    
                                    // Stop all tracks
                                    stream.getTracks().forEach(track => track.stop());
                                    return true;
                                }} catch (error) {{
                                    console.warn('Microphone permission issue:', error.name, error.message);
                                    updateStatus('Microphone access required', 'warning');
                                    updateSessionStatus('Allow microphone access');
                                    
                                    if (error.name === 'NotAllowedError') {{
                                        showError('Microphone access was denied. Please allow microphone access and refresh the page.');
                                    }} else if (error.name === 'NotFoundError') {{
                                        showError('No microphone found. Please connect a microphone and refresh.');
                                    }}
                                    return false;
                                }}
                            }}
                            
                            // Enhanced widget initialization
                            async function initializeWidget() {{
                                const apiKey = '{vapi_public_key}';
                                const assistantId = '{a_id}';
                                
                                if (!apiKey || !assistantId) {{
                                    showError('Interview configuration missing. Please contact support.', false);
                                    return;
                                }}
                                
                                updateStatus('Setting up AI interview system...', 'info');
                                updateSessionStatus('Loading AI system');
                                
                                // Wait for DOM to be fully ready
                                await new Promise(resolve => setTimeout(resolve, 1500));
                                
                                try {{
                                    // Create enhanced widget
                                    const widget = document.createElement('vapi-widget');
                                    const widgetConfig = {{
                                        'public-key': apiKey,
                                        'assistant-id': assistantId,
                                        'mode': 'voice',
                                        'theme': 'dark',
                                        'base-bg-color': '#000000',
                                        'accent-color': '#14B8A6',
                                        'cta-button-color': '#667eea',
                                        'cta-button-text-color': '#ffffff',
                                        'border-radius': 'large',
                                        'size': 'full',
                                        'position': 'center',
                                        'title': 'UPSC MOCK INTERVIEW',
                                        'start-button-text': '🎙️ Begin Interview',
                                        'end-button-text': '📞 End Interview',
                                        'voice-show-transcript': 'true',
                                        'consent-required': 'true',
                                        'consent-title': 'Interview Consent',
                                        'consent-content': 'By proceeding, I consent to the recording and analysis of this mock interview session for assessment purposes in accordance with UPSC Civil Services guidelines.',
                                        'consent-storage-key': 'upsc_interview_consent'
                                    }};
                                    
                                    Object.entries(widgetConfig).forEach(([key, value]) => {{
                                        widget.setAttribute(key, value);
                                    }});
                                    
                                    // Replace loading with widget
                                    const container = document.getElementById('widgetContainer');
                                    container.innerHTML = '';
                                    container.appendChild(widget);
                                    
                                    updateStatus('Interview system ready - Click "Begin Interview"', 'success');
                                    updateSessionStatus('Ready to start');
                                    
                                    // Enhanced widget event listeners
                                    widget.addEventListener('call-start', () => {{
                                        updateStatus('🔴 INTERVIEW IN PROGRESS', 'live');
                                        updateSessionStatus('🔴 Live Interview');
                                        document.title = '🔴 LIVE: UPSC Interview - {candidate_name}';
                                        showSuccess('✅ Interview started successfully! Speak clearly and confidently.');
                                        
                                        // Hide other elements to focus on interview
                                        document.querySelector('.info-grid').style.opacity = '0.3';
                                    }});
                                    
                                    widget.addEventListener('call-end', () => {{
                                        updateStatus('Interview session completed', 'success');
                                        updateSessionStatus('✅ Completed successfully');
                                        document.title = '✅ Completed: UPSC Interview - {candidate_name}';
                                        showSuccess('🎉 Interview completed! Your performance is being analyzed. You may close this window.');
                                        
                                        // Restore visibility
                                        document.querySelector('.info-grid').style.opacity = '1';
                                    }});
                                    
                                    widget.addEventListener('error', (event) => {{
                                        console.error('Widget error details:', event);
                                        updateStatus('Interview system error', 'error');
                                        updateSessionStatus('❌ Technical error');
                                        showError('A technical error occurred. Please refresh and try again, or contact support if the issue persists.');
                                    }});
                                    
                                    // Additional widget events
                                    widget.addEventListener('call-connecting', () => {{
                                        updateStatus('Connecting to interview board...', 'info');
                                        updateSessionStatus('Connecting...');
                                    }});
                                    
                                }} catch (error) {{
                                    console.error('Widget initialization failed:', error);
                                    showError('Failed to initialize the interview system. Please refresh the page and try again.');
                                }}
                            }}
                            
                            // Enhanced SDK loading
                            function loadVapiSDK() {{
                                return new Promise((resolve, reject) => {{
                                    updateStatus('Loading voice SDK...', 'info');
                                    const script = document.createElement('script');
                                    script.src = 'https://unpkg.com/@vapi-ai/client-sdk-react/dist/embed/widget.umd.js';
                                    script.async = true;
                                    script.onload = () => {{
                                        console.log('Vapi SDK loaded successfully');
                                        resolve();
                                    }};
                                    script.onerror = (error) => {{
                                        console.error('SDK loading failed:', error);
                                        reject(new Error('Failed to load voice interface SDK'));
                                    }};
                                    document.head.appendChild(script);
                                }});
                            }}
                            
                            // Main initialization sequence
                            document.addEventListener('DOMContentLoaded', async () => {{
                                try {{
                                    console.log('Starting interview initialization...');
                                    
                                    // Step 1: Check microphone
                                    const micOk = await checkMicrophonePermission();
                                    if (!micOk) {{
                                        console.warn('Microphone check failed, but continuing...');
                                    }}
                                    
                                    // Step 2: Load SDK
                                    updateStatus('Loading advanced voice system...', 'info');
                                    await loadVapiSDK();
                                    
                                    // Step 3: Initialize widget
                                    await initializeWidget();
                                    
                                    console.log('Interview initialization completed successfully');
                                    
                                }} catch (error) {{
                                    console.error('Initialization sequence failed:', error);
                                    showError('Failed to initialize the interview system. Please check your internet connection and try again.');
                                }}
                            }});
                            
                            // Enhanced page lifecycle management
                            window.addEventListener('beforeunload', (event) => {{
                                if (document.title.includes('🔴 LIVE:')) {{
                                    event.preventDefault();
                                    event.returnValue = 'Your UPSC interview is currently in progress. Are you sure you want to leave? This will end your interview session.';
                                    return event.returnValue;
                                }}
                            }});
                            
                            document.addEventListener('visibilitychange', () => {{
                                if (document.hidden && document.title.includes('🔴 LIVE:')) {{
                                    updateStatus('⚠️ Interview paused - window not visible', 'warning');
                                }} else if (!document.hidden && document.title.includes('🔴 LIVE:')) {{
                                    updateStatus('🔴 Interview resumed', 'live');
                                }}
                            }});
                            
                            // Performance monitoring
                            window.addEventListener('load', () => {{
                                console.log('Interview window fully loaded in', performance.now().toFixed(0), 'ms');
                            }});
                        </script>
                    </body>
                    </html>
                    `);
                    popup.document.close();
                    popup.focus();
                    
                    // Enhanced popup monitoring
                    const monitorInterval = setInterval(() => {{
                        if (popup.closed) {{
                            clearInterval(monitorInterval);
                            console.log('Interview window was closed by user');
                        }}
                    }}, 1000);
                    
                }} else {{
                    showPopupBlockedDialog();
                }}
            }}
            
            function showPopupBlockedDialog() {{
                const overlay = document.createElement('div');
                overlay.style.cssText = `
                    position: fixed; top: 0; left: 0; width: 100%; height: 100%;
                    background: rgba(0,0,0,0.8); z-index: 10000; display: flex;
                    align-items: center; justify-content: center;
                `;
                
                const dialog = document.createElement('div');
                dialog.style.cssText = `
                    background: linear-gradient(135deg, #667eea, #764ba2); color: white;
                    padding: 30px; border-radius: 15px; max-width: 500px; width: 90%;
                    text-align: center; box-shadow: 0 20px 40px rgba(0,0,0,0.3);
                    font-family: system-ui; position: relative;
                `;
                
                dialog.innerHTML = `
                    <h3 style="margin-bottom: 20px; font-size: 1.5em;">🚫 Popup Blocked</h3>
                    <p style="margin-bottom: 20px; line-height: 1.5;">
                        For the best interview experience with full microphone access, please:
                    </p>
                    <ol style="text-align: left; margin-bottom: 25px; padding-left: 20px;">
                        <li style="margin: 8px 0;">Click the popup icon (🚫) in your browser's address bar</li>
                        <li style="margin: 8px 0;">Select "Always allow popups from this site"</li>
                        <li style="margin: 8px 0;">Click "Start Interview" again</li>
                    </ol>
                    <div style="display: flex; gap: 15px; justify-content: center; flex-wrap: wrap;">
                        <button onclick="window.open('{create_interview_url(vapi_public_key, a_id, candidate_name, sel)}', '_blank'); document.body.removeChild(this.closest('[style*=\"position: fixed\"]'));" 
                                style="background: #3b82f6; color: white; border: none; padding: 12px 24px; border-radius: 8px; cursor: pointer; font-weight: 600; font-size: 14px;">
                            🌐 Continue in New Tab
                        </button>
                        <button onclick="document.body.removeChild(this.closest('[style*=\"position: fixed\"]'));" 
                                style="background: rgba(255,255,255,0.2); color: white; border: none; padding: 12px 24px; border-radius: 8px; cursor: pointer; font-weight: 600; font-size: 14px;">
                            ✕ Close
                        </button>
                    </div>
                `;
                
                overlay.appendChild(dialog);
                document.body.appendChild(overlay);
                
                // Auto-close after 15 seconds and open in new tab
                setTimeout(() => {{
                    if (document.body.contains(overlay)) {{
                        document.body.removeChild(overlay);
                        window.open('{create_interview_url(vapi_public_key, a_id, candidate_name, sel)}', '_blank');
                    }}
                }}, 15000);
            }}
            
            // Execute the smart launch
            smartInterviewLaunch();
            </script>
            """
            st.components.v1.html(popup_script, height=0)
            st.success("🚀 **Interview launch initiated!** If popup was blocked, it will automatically open in a new tab.")
            st.session_state.interview_status = "active"
    
    with col2:
        external_url = create_interview_url(vapi_public_key, a_id, candidate_name, sel)
        if st.button("🌐 **Backup Method (New Tab)**", use_container_width=True, help="Opens interview in a new browser tab - use if popup is blocked"):
            st.session_state.interview_started_at = dt.datetime.now(dt.timezone.utc).isoformat()
            st.session_state.interview_status = "starting"
            
            new_tab_script = f"""
            <script>
            const newTab = window.open('{external_url}', '_blank');
            if (!newTab) {{
                alert('❌ New tab blocked! Please allow popups or manually copy the interview link.');
            }}
            </script>
            """
            st.components.v1.html(new_tab_script, height=0)
            st.success("🎯 **New tab opened!** Switch to the interview tab to begin.")

    # Additional options
    st.subheader("📱 Additional Options")
    
    col3, col4, col5 = st.columns(3)
    
    with col3:
        mobile_url = create_interview_url(vapi_public_key, a_id, candidate_name, sel, is_mobile=True)
        st.link_button("📱 Mobile Version", mobile_url, use_container_width=True, help="Optimized for mobile devices")
    
    with col4:
        if st.button("📋 Copy Interview Link", use_container_width=True, help="Copy link to clipboard"):
            copy_script = f"""
            <script>
            if (navigator.clipboard) {{
                navigator.clipboard.writeText('{external_url}').then(() => {{
                    alert('✅ Interview link copied to clipboard!');
                }}).catch(() => {{
                    prompt('📋 Copy this link manually:', '{external_url}');
                }});
            }} else {{
                prompt('📋 Copy this link manually:', '{external_url}');
            }}
            </script>
            """
            st.components.v1.html(copy_script, height=0)
    
    with col5:
        if st.button("🔄 Reset Session", help="Clear current session and start fresh"):
            st.session_state.interview_started_at = None
            st.session_state.interview_status = "idle"
            st.success("✅ Session reset successfully.")
            st.rerun()

    # Current session info
    if st.session_state.interview_started_at:
        start_time = dt.datetime.fromisoformat(st.session_state.interview_started_at.replace('Z', '+00:00'))
        elapsed = dt.datetime.now(dt.timezone.utc) - start_time
        
        st.info(f"""
        ⏱️ **Active Session Information:**
        - **Started:** {start_time.strftime('%H:%M:%S UTC')} 
        - **Elapsed:** {str(elapsed).split('.')[0]}
        - **Status:** {st.session_state.interview_status.title()}
        - **Candidate:** {candidate_name}
        """)

    # Enhanced troubleshooting section
    with st.expander("🔧 Troubleshooting & Help", expanded=False):
        st.markdown("""
        ### 🚨 Common Issues & Solutions:
        
        **🎤 Microphone Problems:**
        - **Permission Denied:** Click browser's 🔒 lock icon → Allow microphone
        - **No Audio:** Check system microphone settings and test with other apps
        - **Poor Quality:** Use external microphone or headset
        - **Not Detected:** Try different browser or restart browser completely
        
        **🌐 Browser Issues:**
        - **Popup Blocked:** Look for 🚫 icon in address bar → "Always allow popups"
        - **Widget Won't Load:** Disable ad blockers temporarily
        - **Freezing/Lag:** Close other tabs and applications
        - **Mobile Issues:** Use desktop/laptop for best experience
        
        **📞 Interview Problems:**
        - **Call Drops:** Check internet stability, use wired connection
        - **Audio Delay:** Refresh and try again
        - **Can't Hear Interviewer:** Check speakers/headphones
        - **Interviewer Can't Hear You:** Check microphone permissions and settings
        
        **🔄 If All Else Fails:**
        1. Try different browser (Chrome recommended)
        2. Clear browser cache and cookies
        3. Restart browser completely
        4. Try from different device
        5. Contact technical support with error details
        
        ### ✅ **Recommended Setup:**
        - **Browser:** Chrome 85+ or Firefox 80+
        - **Connection:** Stable broadband (10+ Mbps)
        - **Device:** Desktop/laptop with external microphone
        - **Environment:** Quiet room with good lighting
        """)

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
                
                # Additional resources and downloads
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
                        # Create downloadable transcript
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
                    # Create downloadable feedback report
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
                
                # Performance insights
                structured_data = analysis.get("structuredData") or {}
                if structured_data:
                    with st.expander("📈 Detailed Performance Insights", expanded=False):
                        insight_cols = st.columns(2)
                        with insight_cols[0]:
                            if structured_data.get("strengths"):
                                st.markdown("**🌟 Key Strengths:**")
                                st.success(structured_data["strengths"])
                            if structured_data.get("personalityTraits"):
                                st.markdown("**👤 Personality Assessment:**")
                                st.info(structured_data["personalityTraits"])
                        
                        with insight_cols[1]:
                            if structured_data.get("areasForImprovement"):
                                st.markdown("**🎯 Areas for Improvement:**")
                                st.warning(structured_data["areasForImprovement"])
                            if structured_data.get("overallImpression"):
                                st.markdown("**💭 Overall Impression:**")
                                st.info(structured_data["overallImpression"])
                
                # Update status to completed
                if st.session_state.interview_status in ["starting", "active"]:
                    st.session_state.interview_status = "completed"
                    
        except Exception as e:
            st.error(f"❌ **Error fetching feedback:** {str(e)}")
            st.session_state.interview_status = "error"
            
            # Provide troubleshooting help
            with st.expander("🔧 Troubleshooting Feedback Issues", expanded=True):
                st.markdown("""
                **Common solutions:**
                1. **Wait longer:** Analysis takes 2-3 minutes after interview completion
                2. **Check interview status:** Ensure interview was properly completed
                3. **Refresh manually:** Click "Fetch Latest Feedback" button again
                4. **Verify API keys:** Ensure Vapi API key is correctly configured
                5. **Contact support:** If issue persists, note the error message above
                """)

st.markdown("---")
st.markdown("""
<div style="text-align: center; padding: 20px; background: linear-gradient(135deg, #667eea, #764ba2); border-radius: 15px; color: white;">
    <h4>© Drishti AI Team | UPSC Mock Interview Platform</h4>
    <p>🔒 All interviews are recorded and analyzed for assessment purposes only.</p>
    <p>📞 For technical support: <strong>support@drishti.ai</strong></p>
</div>
""", unsafe_allow_html=True)
