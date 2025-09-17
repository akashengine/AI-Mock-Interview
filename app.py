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
- Build follow-up questions from candidate’s answers.

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
- If candidate says “I don’t know” accept gracefully.
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

SUMMARY_PLAN_MESSAGES=[{"role":"system","content":"You are an expert note-taker.\nYou will be given a transcript of a call. Summarize the call in 2–3 sentences, highlighting:\n- Key topics/questions asked\n- Candidate’s response areas (background, current affairs, ethics, optional subject, hobbies).\n\nOutput: concise, neutral summary (2–3 sentences)."},{"role":"user","content":"Here is the transcript:\n\n{{transcript}}\n\n. Here is the ended reason of the call:\n\n{{endedReason}}\n\n"}]
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

st.markdown("---")
st.header("Step 5 · Start Interview")
if not st.session_state.assistants:
    st.info("Create an assistant first.")
else:
    candidate_keys=list(st.session_state.assistants.keys())
    sel=st.selectbox("Select Candidate", options=candidate_keys, index=candidate_keys.index(st.session_state.current_candidate) if st.session_state.current_candidate in candidate_keys else 0)
    st.session_state.current_candidate=sel
    a_id=st.session_state.assistants[sel]["assistant_id"]

    if st.button("Start Interview Session", type="primary"):
        st.session_state.interview_started_at=dt.datetime.now(dt.timezone.utc).isoformat()

    # Embedded Web SDK controls (start/end/mute/unmute)
    embedded_controls_html=textwrap.dedent(f"""
    <!DOCTYPE html>
    <html>
      <head>
        <meta charset=\"utf-8\" />
        <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
        <style>
          body {{ font-family: system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif; margin: 0; padding: 10px; background: #0b0b0b; color: #f2f2f2; }}
          #controls {{ display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 8px; }}
          button {{ background: #14B8A6; color: #001314; border: 0; padding: 8px 12px; border-radius: 6px; cursor: pointer; }}
          button.secondary {{ background: #333; color: #eee; }}
          pre#log {{ height: 120px; overflow: auto; background: #111; padding: 8px; border-radius: 6px; margin: 0; }}
        </style>
      </head>
      <body>
        <div id=\"controls\">
          <button id=\"start\">Start Call</button>
          <button id=\"end\" class=\"secondary\">End Call</button>
          <button id=\"mute\" class=\"secondary\">Mute</button>
          <button id=\"unmute\" class=\"secondary\">Unmute</button>
        </div>
        <pre id=\"log\"></pre>
        <script>
          const apiKey = \"{vapi_public_key}\";
          const assistantId = \"{a_id}\";
          function log(m) { const el=document.getElementById('log'); el.textContent += m + '\n'; el.scrollTop = el.scrollHeight; }
          function load(src){ return new Promise((res,rej)=>{ const s=document.createElement('script'); s.src=src; s.async=true; s.onload=res; s.onerror=rej; document.head.appendChild(s); }); }
          (async ()=>{
            try {
              await load('https://unpkg.com/@vapi-ai/web/dist/index.umd.js');
              const Vapi = window.Vapi?.default || window.Vapi;
              const vapi = new Vapi(apiKey);
              window._vapi=vapi;
              document.getElementById('start').onclick=()=>vapi.start(assistantId);
              document.getElementById('end').onclick=()=>vapi.stop();
              document.getElementById('mute').onclick=()=>vapi.mute();
              document.getElementById('unmute').onclick=()=>vapi.unmute();
              vapi.on('call-start', ()=>log('call-start'));
              vapi.on('call-end', ()=>log('call-end'));
              vapi.on('message', (m)=>{ if(m.type==='transcript'){ log(`${m.role}: ${m.transcript}`); }});
              log('Web SDK ready. Click Start Call and allow mic.');
            } catch(e) { log('Failed to load Web SDK: '+e); }
          })();
        </script>
      </body>
    </html>
    """)
    st.components.v1.html(embedded_controls_html, height=260)

    # Full-screen Web SDK page in a new tab as fallback
    page_template=textwrap.dedent(f"""
    <!DOCTYPE html>
    <html>
      <head>
        <meta charset=\"utf-8\" />
        <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
        <title>UPSC Interview – Voice Call</title>
        <style>
          body {{ font-family: system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif; margin: 0; padding: 16px; background: #0b0b0b; color: #f2f2f2; }}
          #controls {{ display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 8px; }}
          button {{ background: #14B8A6; color: #001314; border: 0; padding: 10px 14px; border-radius: 6px; cursor: pointer; }}
          button.secondary {{ background: #333; color: #eee; }}
          pre#log {{ height: 160px; overflow: auto; background: #111; padding: 8px; border-radius: 6px; margin: 0; }}
        </style>
      </head>
      <body>
        <h3>UPSC Interview – Voice Call</h3>
        <p>Please allow microphone access when prompted.</p>
        <div id=\"controls\">
          <button id=\"start\">Start Call</button>
          <button id=\"end\" class=\"secondary\">End Call</button>
          <button id=\"mute\" class=\"secondary\">Mute</button>
          <button id=\"unmute\" class=\"secondary\">Unmute</button>
        </div>
        <pre id=\"log\"></pre>
        <script>
          const apiKey = \"{vapi_public_key}\";
          const assistantId = \"{a_id}\";
          function log(m) { const el=document.getElementById('log'); el.textContent += m + '\n'; el.scrollTop = el.scrollHeight; }
          function load(src){ return new Promise((res,rej)=>{ const s=document.createElement('script'); s.src=src; s.async=true; s.onload=res; s.onerror=rej; document.head.appendChild(s); }); }
          (async ()=>{
            try {
              await load('https://unpkg.com/@vapi-ai/web/dist/index.umd.js');
              const Vapi = window.Vapi?.default || window.Vapi;
              const vapi = new Vapi(apiKey);
              window._vapi=vapi;
              document.getElementById('start').onclick=()=>vapi.start(assistantId);
              document.getElementById('end').onclick=()=>vapi.stop();
              document.getElementById('mute').onclick=()=>vapi.mute();
              document.getElementById('unmute').onclick=()=>vapi.unmute();
              vapi.on('call-start', ()=>log('call-start'));
              vapi.on('call-end', ()=>log('call-end'));
              vapi.on('message', (m)=>{ if(m.type==='transcript'){ log(`${m.role}: ${m.transcript}`); }});
              log('Web SDK ready. Click Start Call and allow mic.');
            } catch(e) { log('Failed to load Web SDK: '+e); }
          })();
        </script>
      </body>
    </html>
    """)
    data_url="data:text/html;base64,"+base64.b64encode(page_template.encode()).decode()
    st.link_button("Open Web SDK in New Tab", data_url, type="secondary")
    st.caption("Prefer the new tab if the embedded controls cannot access the microphone.")

st.markdown("---")
st.header("Step 6 · Fetch & Display Feedback")
auto=st.checkbox("Auto-refresh every 5s", value=False)
fetch_now=st.button("Fetch Latest Feedback For Selected Candidate", type="primary")
if auto:
    time.sleep(5)
    st.experimental_rerun()

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
                st.info("No finished calls yet. Keep this section open and refresh.")
            else:
                call=fetch_call(vapi_api_key, latest["id"])
                analysis=call.get("analysis") or {}
                summary=analysis.get("summary") or ""
                success=analysis.get("successEvaluation") or {}
                df=flatten_feedback_for_table(call)
                st.subheader("Interview Feedback")
                if summary:
                    st.write(summary)
                st.table(df)
                rating=None; justification=None
                if isinstance(success, dict):
                    rating=success.get("overallRating")
                    justification=success.get("justification") or success.get("reason")
                elif success:
                    rating=str(success)
                if rating:
                    msg=f"Overall Success Rating: {rating}"
                    if rating in ["Highly Suitable","Suitable"]:
                        st.success(msg)
                    elif rating in ["Borderline"]:
                        st.warning(msg)
                    elif rating in ["Unsuitable"]:
                        st.error(msg)
                    else:
                        st.info(msg)
                    if justification:
                        st.caption(justification)
                artifact=call.get("artifact") or {}
                rec=(artifact.get("recording") or {}).get("mono") or {}
                if rec.get("combinedUrl"): st.link_button("Download Recording", rec["combinedUrl"], type="secondary")
                if artifact.get("transcript"):
                    with st.expander("Transcript"): st.text(artifact["transcript"])
        except Exception as e:
            st.error(str(e))

st.markdown("---"); st.caption("© Drishti AI Team")
