import streamlit as st
import json
from pathlib import Path
from datetime import datetime
import streamlit.components.v1 as components
from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError

# Read MongoDB URL from secrets
mongo_uri = st.secrets["mongo_uri"]
client = MongoClient(mongo_uri)
db = client["msme_schemes_db"]
schemes_coll = db["schemes"]
locks_coll = db["locks"]
logs_coll = db["user_logs"]

st.sidebar.subheader("👤 Enter Your Name")
current_user = st.sidebar.text_input("Your full name", "")
if not current_user:
    st.sidebar.warning("Please type your name before proceeding.")
    st.stop()

def acquire_lock(scheme_id: str, user: str) -> bool:
    now = datetime.utcnow()
    lock_doc = locks_coll.find_one({"scheme_id": scheme_id})
    if lock_doc:
        if (now - lock_doc["locked_at"]).total_seconds() > 300:
            locks_coll.replace_one({"scheme_id": scheme_id}, {"scheme_id": scheme_id, "locked_by": user, "locked_at": now})
            return True
        if lock_doc["locked_by"] == user:
            locks_coll.update_one({"scheme_id": scheme_id}, {"$set": {"locked_at": now}})
            return True
        return False
    else:
        locks_coll.insert_one({"scheme_id": scheme_id, "locked_by": user, "locked_at": now})
        return True

# Title and initial DB check
st.title("📋 MSME Scheme Editor Tool")
data_file = Path("definitely_final.json")
if schemes_coll.estimated_document_count() == 0:
    if data_file.exists():
        with open(data_file, "r", encoding="utf-8") as f:
            json_schemes = json.load(f)
        schemes_coll.insert_many(json_schemes)
        st.success("✅ Data seeded from definitely_final.json to MongoDB.")
        st.rerun()
    else:
        st.error("Scheme data file not found, and MongoDB is empty!")
        st.stop()

schemes_cursor = schemes_coll.find({})
all_schemes = list(schemes_cursor)
scheme_ids = [doc["scheme_id"] for doc in all_schemes]
if not scheme_ids:
    st.error("No schemes available in the database.")
    st.stop()

selected_id = st.selectbox("Select Scheme ID", scheme_ids)
if "new_scheme" in st.session_state:
    if selected_id != st.session_state["new_scheme"].get("scheme_id", ""):
        del st.session_state["new_scheme"]

col1, col2 = st.columns(2)
with col1:
    if st.button("➕ Add New Scheme"):
        st.session_state["new_scheme"] = {
            "scheme_id": "", "jurisdiction": "", "scheme_name": "", "category": "",
            "status": "", "ministry": "", "target_group": "", "objective": "",
            "eligibility": "", "assistance": [], "key_benefits": "", "how_to_apply": "",
            "required_documents": [], "tags": "", "sources": "",
            "last_modified_by": None, "last_modified_at": None
        }

with col2:
    if st.button("🗑️ Delete This Scheme"):
        confirm = st.checkbox(f"Confirm deletion of '{selected_id}'", key="confirm_delete")
        if confirm:
            schemes_coll.delete_one({"scheme_id": selected_id})
            logs_coll.insert_one({
                "scheme_id": selected_id, "user": current_user,
                "action": "deleted", "timestamp": datetime.utcnow()
            })
            st.success(f"🗑️ Scheme '{selected_id}' deleted from MongoDB.")
            st.rerun()

is_new = "new_scheme" in st.session_state
scheme = st.session_state["new_scheme"] if is_new else schemes_coll.find_one({"scheme_id": selected_id})

if not scheme:
    st.error(f"Scheme '{selected_id}' not found in the database.")
    st.stop()

st.subheader("🆕 Add New Scheme" if is_new else f"📝 Edit Scheme Details: {selected_id}")

if not is_new and not acquire_lock(selected_id, current_user):
    st.error("🚫 This scheme is currently being edited by someone else. Please try again later.")
    st.stop()

if not is_new:
    last_log = logs_coll.find_one({"scheme_id": selected_id}, sort=[("timestamp", -1)])
    if last_log:
        st.info(f"🕒 Last updated by **{last_log['user']}** on **{last_log['timestamp'].strftime('%Y-%m-%d %H:%M:%S')}**")
    else:
        st.info("ℹ️ This scheme has never been edited yet.")

with st.form("edit_form"):
    scheme["scheme_id"] = st.text_input("scheme_id", scheme.get("scheme_id", ""), disabled=not is_new)
    for key, value in scheme.items():
        if key == "scheme_id":
            continue
        if isinstance(value, list):
            lines = st.text_area(key, "\n".join(value))
            scheme[key] = [line.strip() for line in lines.splitlines() if line.strip()]
        else:
            scheme[key] = st.text_area(key, value or "", height=100)

    if st.form_submit_button("💾 Save Changes"):
        scheme["last_modified_by"] = current_user
        scheme["last_modified_at"] = datetime.utcnow()
        if is_new:
            if not scheme["scheme_id"]:
                st.error("⚠️ scheme_id cannot be blank.")
            elif schemes_coll.find_one({"scheme_id": scheme["scheme_id"]}):
                st.error("⚠️ That scheme_id already exists. Choose a different one.")
            else:
                schemes_coll.insert_one(scheme)
                logs_coll.insert_one({"scheme_id": scheme["scheme_id"], "user": current_user, "action": "created", "timestamp": datetime.utcnow()})
                del st.session_state["new_scheme"]
                st.success(f"✅ Scheme '{scheme['scheme_id']}' added.")
                st.rerun()
        else:
            scheme.pop("_id", None)
            schemes_coll.replace_one({"scheme_id": selected_id}, scheme)
            locks_coll.delete_one({"scheme_id": selected_id})
            logs_coll.insert_one({"scheme_id": selected_id, "user": current_user, "action": "edited", "timestamp": datetime.utcnow()})
            st.success("✅ Scheme updated and lock released.")
            st.rerun()

# Missing fields prompt generator
missing_keys = [k for k, v in scheme.items() if v in (None, [], "") and k not in ("scheme_id", "tags")]
prompt = f'''
You are assisting in curating structured and verified data for an Indian government scheme chatbot.

Scheme Details:
- scheme_id: "{scheme.get("scheme_id", "")}"
- scheme_name: "{scheme.get("scheme_name", "")}"

The following fields are missing and need to be filled individually and in detail:
{chr(10).join([f"- {key}" for key in missing_keys])}

Guidelines:
- ✅ Use only official sources such as ministry portals, mygov.in, india.gov.in, PIB, or official PDF guidelines.
- ✅ Be as detailed and specific as possible for each field.
- ✅ Use bullet points where helpful.
- ❌ Do not include or generate the `tags` field.
- ❌ Do not hallucinate. Leave a field blank if no official info is found.
- ✅ At the end, include a `sources` field listing all URLs or PDFs used (one list for all, not per field).

---

Format your output like:

{{
  "objective": "• content\\n• more",
  "eligibility": "• eligibility 1\\n• eligibility 2",
  "key_benefits": "• benefit 1\\n• benefit 2",
  "how_to_apply": "• step 1\\n• step 2",
  "required_documents": "• doc 1\\n• doc 2",
  "sources": [
    "https://official-source-1",
    "https://official-source-2"
  ]
}}
'''.strip()

st.subheader("🤖 Copy Final Prompt + Scheme")
components.html(f"""
    <textarea id='fullPrompt' style='display:none;'>{prompt}</textarea>
    <button onclick="navigator.clipboard.writeText(document.getElementById('fullPrompt').value); alert('Full prompt copied to clipboard!');">
        📋 Copy Prompt for ChatGPT
    </button>
""", height=100)

st.subheader("🔍 Fields with Missing Information")
if missing_keys:
    st.warning(f"Missing fields: {', '.join(missing_keys)}")
else:
    st.success("All fields are filled ✅")
