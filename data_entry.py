import streamlit as st
import json
from pathlib import Path
from datetime import datetime
import streamlit.components.v1 as components
from pymongo import MongoClient
from pymongo.errors import BulkWriteError

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
data_file = Path("F_sources_updated.json")
if schemes_coll.estimated_document_count() == 0:
    if data_file.exists():
        with open(data_file, "r", encoding="utf-8") as f:
            json_schemes = json.load(f)

        # Remove duplicate documents based on scheme_id
        existing_ids = set(doc["scheme_id"] for doc in schemes_coll.find({}, {"scheme_id": 1}))
        unique_docs = []
        duplicate_ids = []
        for doc in json_schemes:
            doc.pop("_id", None)
            if doc["scheme_id"] not in existing_ids:
                existing_ids.add(doc["scheme_id"])
                unique_docs.append(doc)
            else:
                duplicate_ids.append(doc["scheme_id"])

        try:
            if unique_docs:
                schemes_coll.insert_many(unique_docs)
                st.success(f"✅ Inserted {len(unique_docs)} unique schemes into MongoDB.")
            if duplicate_ids:
                st.warning(f"⚠️ Skipped {len(duplicate_ids)} duplicates: {', '.join(duplicate_ids)}")
            st.rerun()
        except BulkWriteError as bwe:
            st.error(f"MongoDB BulkWriteError: {bwe.details}")
            st.stop()
    else:
        st.error("Scheme data file not found, and MongoDB is empty!")
        st.stop()

scheme_ids = [doc["scheme_id"] for doc in schemes_coll.find({}, {"scheme_id": 1})]

search_id = st.text_input("🔍 Search Scheme ID (case-insensitive)").strip().lower()

selected_id = None
if search_id:
    matching = next((sid for sid in scheme_ids if sid.lower() == search_id), None)
    if matching:
        selected_id = matching
    else:
        st.warning("No exact match found for scheme ID.")
        st.stop()


if "new_scheme" in st.session_state:
    if selected_id != st.session_state["new_scheme"].get("scheme_id", ""):
        del st.session_state["new_scheme"]

if not selected_id:
    st.stop()


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

# Prompt generation with dynamic required fields
required_fields = ["objective", "eligibility", "key_benefits", "how_to_apply", "required_documents"]
missing_keys = [k for k in required_fields if not scheme.get(k)]
missing_keys += ["category", "sources"]  # always include these

st.subheader("🔍 Missing Fields Info")
if missing_keys:
    st.info(f"Missing fields: {', '.join(missing_keys)}")
else:
    st.success("All key fields are filled ✅")

scheme_copy = {k: v for k, v in scheme.items() if k != "_id" and k != "tags"}

prompt = f'''
You are assisting in curating structured and verified data for an Indian government scheme chatbot.

Instructions:
- For each required field ({', '.join(f'`{k}`' for k in missing_keys)}), return a separate block with only that field filled.
- Do not include the `tags` field.
- After providing all the individual blocks, provide a single block at the end with:
   - `category`: A list of 1 or more categories (maximum 6) chosen **only** from this list:
    ["Business & Industry", "Employment & Livelihood", "Education & Training", "Women Empowerment", "Minority & Social Welfare", "Health & Insurance", "Environment & Energy", "Research & Innovation", "Infrastructure", "Agriculture & Allied Sectors", "Technology & Digital Economy", "Marketing & Trade", "Skill Development", "Rural Development", "Subsidy", "Grant", "Loan", "Interest Subvention", "Reimbursement", "Incentive", "Seed Capital", "Guarantee Scheme", "Capital Investment Support", "Tax Exemption", "Skill Training", "Incubation", "Infrastructure Support", "Marketing Support", "Patent/Certification Reimbursement", "MSME", "SC/ST", "Minorities", "Women Entrepreneurs", "First-Generation Entrepreneurs", "Startups", "Youth", "Farmers/FPOs", "Handicraft/Artisan Groups", "Rural Enterprises", "Textiles", "Food Processing", "Poultry", "Dairy", "Handlooms & Khadi", "Electronics", "Automobile/EV", "IT/ITES", "Coir Sector", "Logistics", "Export Promotion", "E-waste", "Clean Energy", "Innovation", "Agri-Tech", "Retail & Distribution", "Manufacturing", "Traditional Industries", "Research Institutions"]

   - `sources`: All official sources used for reference.

Rules:
- Use only official Indian government sources (e.g., ministry portals, india.gov.in, mygov.in, PIB).
- Be as detailed and specific as possible. Use bullet points where helpful.
- Leave a field blank if no official info is found.
- Output only the required blocks — no markdown, no explanation.

Format for each field (example for `objective`):

  "objective": "• content\\n• more details"

...repeat for each field...

At the end, provide:

  "sources": 
    "https://official-source-1",
    "https://official-source-2"
  

Here is the scheme to process:

{json.dumps(scheme_copy, indent=2, ensure_ascii=False)}
'''.strip()



st.subheader("🤖 Copy Final Prompt + Scheme")
components.html(f"""
    <textarea id='fullPrompt' style='display:none;'>{prompt}</textarea>
    <button onclick="navigator.clipboard.writeText(document.getElementById('fullPrompt').value); alert('Full prompt copied to clipboard!');">
        📋 Copy Prompt for ChatGPT
    </button>
""", height=120)
