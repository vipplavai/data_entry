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

# Page configuration and styled header
st.set_page_config(
    page_title="MSME Scheme Editor",
    page_icon="📋",
    layout="wide"
)
st.markdown(
    "<h1 style='text-align: center; color: #4B426D; font-family: sans-serif;'>📋 MSME Scheme Editor Tool</h1>",
    unsafe_allow_html=True
)
# --- Add this CSS block for a light, neutral background and modern container look ---
# --- Replace your existing CSS block with this updated version ---
st.markdown(
    """
    <style>
      /* Apply a light-gray background to the entire app */
      .stApp {
          background-color: #F0F2F6;
      }

      /* Make the main container card-like */
      .css-1d391kg {
          background-color: #FFFFFF;
          border-radius: 12px;
          padding: 1.5rem;
          box-shadow: 0 4px 12px rgba(0, 0, 0, 0.05);
      }


      /* ==== Force all Streamlit text areas to fill their parent width ==== */
      .stTextArea > div > textarea {
          background-color: #FFFFFF !important;
          border: 1px solid #ccc !important;
          border-radius: 4px !important;
          width: 100% !important;
          min-width: 100% !important;
          box-sizing: border-box !important;
          resize: vertical; /* allow vertical resizing only */
      }

      /* Also style any “unstyled” <textarea> just in case */
      textarea {
          background-color: #FFFFFF !important;
          border: 1px solid #ccc !important;
          border-radius: 4px !important;
          width: 100% !important;
          min-width: 100% !important;
          box-sizing: border-box !important;
      }

      /* Streamlit text inputs (single line) */
      .stTextInput > div > input {
          background-color: #FFFFFF !important;
          border: 1px solid #ccc !important;
          border-radius: 4px !important;
          width: 100% !important;
          box-sizing: border-box !important;
      }

      /* Streamlit select boxes */
      .stSelectbox > div > * {
          background-color: #FFFFFF !important;
          border: 1px solid #ccc !important;
          border-radius: 4px !important;
          width: 100% !important;
          box-sizing: border-box !important;
      }


      /* ==== Key-value wrapper as a full-width, white box with light border ==== */
      .key-value-box {
          display: block !important;
          width: 100% !important;
          box-sizing: border-box !important;
          border: 1px solid #E0E0E0;
          border-radius: 6px;
          padding: 0.75rem;
          margin-bottom: 0.75rem;
          background-color: #FFFFFF;
      }

      /* ==== Prevent expander header label from stacking vertically ==== */
      /* As of Streamlit mid-2025, the class for the header is stExpanderHeader */
      .stExpanderHeader, .streamlit-expanderHeader {
          flex-direction: row !important;
      }
    </style>
    """,
    unsafe_allow_html=True
)



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

# --- Sidebar search for Scheme ID ---
with st.sidebar.container():
    st.sidebar.subheader("🔍 Find a Scheme")
    search_input = st.sidebar.text_input(
        "Scheme ID (case-insensitive)",
        value="",
        help="Type the scheme_id exactly, then click 'Search'"
    ).strip().lower()

    if st.sidebar.button("🔎 Search"):
        if search_input:
            match = next((sid for sid in scheme_ids if sid.lower() == search_input), None)
            if match:
                st.session_state["selected_id"] = match
            else:
                st.sidebar.warning("No exact match found.")
        else:
            st.sidebar.info("Please type a scheme_id first.")
    # If the user hasn't searched yet, default to any existing session state
selected_id = st.session_state.get("selected_id", None)


if "new_scheme" in st.session_state:
    if selected_id != st.session_state["new_scheme"].get("scheme_id", ""):
        del st.session_state["new_scheme"]

if not selected_id:
    st.stop()


# --- Button bar for Add / Delete, styled as a horizontal container ---
button_col1, button_col2, _ = st.columns([1, 1, 2])

with button_col1:
    if st.button(
          label="➕ Add New Scheme",
          key="create_scheme_btn",
          help="Click to add a brand‐new scheme",
    ):
        st.session_state["new_scheme"] = {
            "scheme_id": "", "jurisdiction": "", "scheme_name": "", "category": "",
            "status": "", "ministry": "", "target_group": "", "objective": "",
            "eligibility": "", "assistance": [], "key_benefits": "", "how_to_apply": "",
            "required_documents": [], "tags": "", "sources": "",
            "last_modified_by": None, "last_modified_at": None
        }

with button_col2:
    if st.button(
          label="🗑️ Delete This Scheme",
          key="delete_scheme_btn",
          help="Permanently remove selected scheme",
          args=(),
          kwargs={},
    ):
        confirm = st.checkbox(
            f"Confirm deletion of '{selected_id}'",
            key="confirm_delete"
        )
        if confirm:
            schemes_coll.delete_one({"scheme_id": selected_id})
            logs_coll.insert_one({
                "scheme_id": selected_id, "user": current_user,
                "action": "deleted", "timestamp": datetime.utcnow()
            })
            st.success(f"🗑️ Scheme '{selected_id}' deleted.")
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
    # --- Top row: one‐line fields ---
    gen_col1, gen_col2 = st.columns(2)
    with gen_col1:
        st.markdown("<div class='key-value-box'>", unsafe_allow_html=True)
        scheme["scheme_id"] = st.text_input(
            label="Scheme ID",
            value=scheme.get("scheme_id", ""),
            disabled=not is_new,
            help="Unique identifier (cannot be edited if already exists)."
        )
        st.markdown("</div>", unsafe_allow_html=True)

        st.markdown("<div class='key-value-box'>", unsafe_allow_html=True)
        scheme["jurisdiction"] = st.text_input(
            label="Jurisdiction",
            value=scheme.get("jurisdiction", ""),
            help="Geographic or administrative jurisdiction."
        )
        st.markdown("</div>", unsafe_allow_html=True)

        st.markdown("<div class='key-value-box'>", unsafe_allow_html=True)
        scheme["scheme_name"] = st.text_input(
            label="Scheme Name",
            value=scheme.get("scheme_name", ""),
            help="Official scheme title."
        )
        st.markdown("</div>", unsafe_allow_html=True)

    with gen_col2:
        st.markdown("<div class='key-value-box'>", unsafe_allow_html=True)
        scheme["category"] = st.text_input(
            label="Category",
            value=scheme.get("category", ""),
            help="Comma‐separated categories (up to 6)."
        )
        st.markdown("</div>", unsafe_allow_html=True)

        st.markdown("<div class='key-value-box'>", unsafe_allow_html=True)
        scheme["status"] = st.selectbox(
            label="Status",
            options=["Active", "Inactive", "Pending", ""],
            index=(["Active", "Inactive", "Pending", ""].index(scheme.get("status", "")) 
                if scheme.get("status", "") in ["Active","Inactive","Pending"] else 3),
            help="Current status of the scheme."
        )
        st.markdown("</div>", unsafe_allow_html=True)

        st.markdown("<div class='key-value-box'>", unsafe_allow_html=True)
        scheme["ministry"] = st.text_input(
            label="Ministry",
            value=scheme.get("ministry", ""),
            help="Overseeing government ministry."
        )
        st.markdown("</div>", unsafe_allow_html=True)


    # --- Tabs for the longer text / lists ---
    tab_general, tab_details = st.tabs(["General Info", "Core Details"])

    with tab_general:
        st.markdown("<div class='key-value-box'>", unsafe_allow_html=True)
        scheme["target_group"] = st.text_input(
            label="Target Group",
            value=scheme.get("target_group", ""),
            help="Who is eligible (e.g., Women Entrepreneurs, MSMEs)."
        )
        st.markdown("</div>", unsafe_allow_html=True)

        st.markdown("<div class='key-value-box'>", unsafe_allow_html=True)
        scheme["objective"] = st.text_area(
            label="Objective",
            value=scheme.get("objective", ""),
            height=120,
            help="Purpose of the scheme (use bullet points if needed)."
        )
        st.markdown("</div>", unsafe_allow_html=True)


        # --- Wrap ONLY the textarea inside the Eligibility expander ---
        with st.expander("► Eligibility Criteria"):
            existing = "\n".join(scheme.get("eligibility", []))

            # open the white‐background box
            st.markdown("<div class='key-value-box'>", unsafe_allow_html=True)
            lines = st.text_area(
                label="Eligibility Criteria",
                value=existing,
                height=200,
                help="Enter each eligibility criterion on its own line.",
                key="eligibility_area"
            )
            scheme["eligibility"] = [ln.strip() for ln in lines.splitlines() if ln.strip()]

            # close the white‐background box
            st.markdown("</div>", unsafe_allow_html=True)


        # --- Wrap ONLY the textarea inside the Assistance expander ---
        with st.expander("► Assistance Details"):
            existing = "\n".join(scheme.get("assistance", []))

            # open the white‐background box
            st.markdown("<div class='key-value-box'>", unsafe_allow_html=True)
            lines = st.text_area(
                label="Assistance Details",
                value=existing,
                height=200,
                help="List each assistance point on its own line.",
                key="assistance_area"
            )
            scheme["assistance"] = [ln.strip() for ln in lines.splitlines() if ln.strip()]

            # close the white‐background box
            st.markdown("</div>", unsafe_allow_html=True)





    with tab_details:
        with st.expander("► Key Benefits"):
            st.markdown("<div class='key-value-box'>", unsafe_allow_html=True)
            scheme["key_benefits"] = st.text_area(
                label="Key Benefits",
                value=scheme.get("key_benefits", ""),
                height=120,
                help="List key advantages (one bullet per line)."
            )
            st.markdown("</div>", unsafe_allow_html=True)

        with st.expander("► How to Apply"):
            st.markdown("<div class='key-value-box'>", unsafe_allow_html=True)
            scheme["how_to_apply"] = st.text_area(
                label="How to Apply",
                value=scheme.get("how_to_apply", ""),
                height=120,
                help="Steps for application process."
            )
            st.markdown("</div>", unsafe_allow_html=True)

        with st.expander("► Required Documents"):
            st.markdown("<div class='key-value-box'>", unsafe_allow_html=True)
            existing = "\n".join(scheme.get("required_documents", []))
            lines = st.text_area(
                label="Required Documents",
                value=existing,
                height=120,
                help="Enter each required document on its own line."
            )
            scheme["required_documents"] = [ln.strip() for ln in lines.splitlines() if ln.strip()]
            st.markdown("</div>", unsafe_allow_html=True)


        st.markdown("<div class='key-value-box'>", unsafe_allow_html=True)
        scheme["tags"] = st.text_input(
            label="Tags",
            value=scheme.get("tags", ""),
            help="Any comma‐separated tags for search‐filtering."
        )
        st.markdown("</div>", unsafe_allow_html=True)

        st.markdown("<div class='key-value-box'>", unsafe_allow_html=True)
        scheme["sources"] = st.text_input(
            label="Sources (comma‐separated URLs)",
            value=scheme.get("sources", ""),
            help="Official reference URLs (e.g., gov.in, mygov.in)."
        )
        st.markdown("</div>", unsafe_allow_html=True)


    # --- Save / Cancel Buttons at the bottom ---
    save_col, cancel_col = st.columns([1, 1])
    with save_col:
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
                    logs_coll.insert_one({
                        "scheme_id": scheme["scheme_id"],
                        "user": current_user,
                        "action": "created",
                        "timestamp": datetime.utcnow()
                    })
                    del st.session_state["new_scheme"]
                    st.success(f"✅ Scheme '{scheme['scheme_id']}' added.")
                    st.rerun()
            else:
                scheme.pop("_id", None)
                schemes_coll.replace_one({"scheme_id": selected_id}, scheme)
                locks_coll.delete_one({"scheme_id": selected_id})
                logs_coll.insert_one({
                    "scheme_id": selected_id,
                    "user": current_user,
                    "action": "edited",
                    "timestamp": datetime.utcnow()
                })
                st.success("✅ Scheme updated and lock released.")
                st.rerun()

    with cancel_col:
        if st.form_submit_button("✖ Cancel"):
            if is_new:
                del st.session_state["new_scheme"]
            else:
                locks_coll.delete_one({"scheme_id": selected_id})
            st.info("Edit cancelled.")
            st.rerun()


# Prompt generation with dynamic required fields
required_fields = ["objective", "eligibility", "key_benefits", "how_to_apply", "required_documents", "category", "sources"]
missing_keys = [k for k in required_fields if scheme.get(k) in (None, "", [], {})]

# missing_keys += ["category", "sources"]  # always include these

# --- Missing or Complete Fields Banner ---
with st.container():
    if missing_keys:
        st.markdown(
            f"<div style='background-color:#FFF4E5; padding:1rem; border-left:4px solid #FFA500; border-radius:8px;'>"
            f"🔍 <strong>Missing fields:</strong> {', '.join(missing_keys)}</div>",
            unsafe_allow_html=True
        )
    else:
        st.markdown(
            "<div style='background-color:#E8F5E9; padding:1rem; border-left:4px solid #4CAF50; border-radius:8px;'>"
            "✅ <strong>All key fields are filled.</strong></div>",
            unsafe_allow_html=True
        )


scheme_copy = {k: v for k, v in scheme.items() if k != "_id" and k != "tags"}

prompt = f'''
You are assisting in curating structured and verified data for an Indian government scheme chatbot.

Instructions:
- For each required field ({', '.join(f'`{k}`' for k in missing_keys)}), return a separate block with only that field filled.
- Do not include the `tags` field.
- For Category and sources:
    - `category`: A list of 1 or more categories (maximum 6) chosen **only** from this list:
        ["Business & Industry", "Employment & Livelihood", "Education & Training", "Women Empowerment", "Minority & Social Welfare", "Health & Insurance", "Environment & Energy", "Research & Innovation", "Infrastructure", "Agriculture & Allied Sectors", "Technology & Digital Economy", "Marketing & Trade", "Skill Development", "Rural Development", "Subsidy", "Grant", "Loan", "Interest Subvention", "Reimbursement", "Incentive", "Seed Capital", "Guarantee Scheme", "Capital Investment Support", "Tax Exemption", "Skill Training", "Incubation", "Infrastructure Support", "Marketing Support", "Patent/Certification Reimbursement", "MSME", "SC/ST", "Minorities", "Women Entrepreneurs", "First-Generation Entrepreneurs", "Startups", "Youth", "Farmers/FPOs", "Handicraft/Artisan Groups", "Rural Enterprises", "Textiles", "Food Processing", "Poultry", "Dairy", "Handlooms & Khadi", "Electronics", "Automobile/EV", "IT/ITES", "Coir Sector", "Logistics", "Export Promotion", "E-waste", "Clean Energy", "Innovation", "Agri-Tech", "Retail & Distribution", "Manufacturing", "Traditional Industries", "Research Institutions"]
    - If the category is already present, check and validate if the category value is valid or not.,
        If invalid or empty, update the category with the right values,
        If valid, check and add additional categories if necessary.
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



st.subheader("🤖 Generate & Copy Prompt")

# Place prompt in a hidden textarea inside a styled container
components.html(
    f"""
    <div style="display:flex; align-items:center; margin-bottom:1rem;">
      <textarea id='fullPrompt' style='display:none;'>{prompt}</textarea>
      <button
        style='
          background-color:#4B426D;
          color:white;
          border:none;
          border-radius:8px;
          padding:0.75rem 1.5rem;
          font-size:1rem;
          cursor:pointer;
        '
        onclick="navigator.clipboard.writeText(document.getElementById('fullPrompt').value);
                 this.innerText='✅ Copied!';"
      >
        📋 Copy Prompt for ChatGPT
      </button>
    </div>
    """,
    height=80
)
st.markdown(
    "<small style='color:#555;'>Use this prompt in ChatGPT to fill in missing fields automatically.</small>",
    unsafe_allow_html=True
)
