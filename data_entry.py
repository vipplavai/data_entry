import streamlit as st
import json
import pandas as pd
from pathlib import Path
from datetime import datetime
import streamlit.components.v1 as components
from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError


# — Read MongoDB URL from secrets.toml —
mongo_uri = st.secrets["mongo_uri"]

# Establish a single MongoClient for the entire app
client = MongoClient(mongo_uri)
db = client["msme_schemes_db"]            # database
schemes_coll = db["schemes"]               # holds each scheme document
locks_coll = db["locks"]                   # for concurrency locks
logs_coll = db["user_logs"]                # record who edited what, when
users_coll = db["users"]                   # (optional) store user info if desired

# =============================================================================
# 1) Prompt the user for their name (required for all subsequent actions)
# =============================================================================
st.sidebar.subheader("👤 Enter Your Name")
current_user = st.sidebar.text_input("Your full name", "")
if not current_user:
    st.sidebar.warning("Please type your name before proceeding.")
    st.stop()


# =============================================================================
# 2) Define helper: acquire_lock
# =============================================================================
def acquire_lock(scheme_id: str, user: str) -> bool:
    """
    Attempts to lock a scheme_id for this user. If locked by someone else in the last 5 minutes, return False.
    Otherwise, upsert a lock document with {scheme_id, locked_by, locked_at}.
    """
    now = datetime.utcnow()
    lock_doc = locks_coll.find_one({"scheme_id": scheme_id})

    if lock_doc:
        locked_at = lock_doc["locked_at"]
        locked_by = lock_doc["locked_by"]
        # If this lock is older than 5 minutes, consider it expired.
        if (now - locked_at).total_seconds() > 300:
            # Overwrite the expired lock
            locks_coll.replace_one(
                {"scheme_id": scheme_id},
                {"scheme_id": scheme_id, "locked_by": user, "locked_at": now}
            )
            return True
        # If locked by the same user, refresh the timestamp
        if locked_by == user:
            locks_coll.update_one(
                {"scheme_id": scheme_id},
                {"$set": {"locked_at": now}}
            )
            return True
        # Locked by someone else and not expired:
        return False
    else:
        # No lock exists — create one
        locks_coll.insert_one(
            {"scheme_id": scheme_id, "locked_by": user, "locked_at": now}
        )
        return True


# =============================================================================
# 3) Title
# =============================================================================
st.title("📋 MSME Scheme Editor Tool")


# =============================================================================
# 4) Load Data from JSON (fallback) and/or MongoDB
# =============================================================================
data_file = Path("definitely_final.json")

# 4.1) If MongoDB is empty, seed it from JSON once
if schemes_coll.count_documents({}) == 0:
    if data_file.exists():
        with open(data_file, "r", encoding="utf-8") as f:
            json_schemes = json.load(f)
        for s in json_schemes:
            try:
                schemes_coll.insert_one(s)
            except DuplicateKeyError:
                pass
    else:
        st.error("Scheme data file not found, and MongoDB is empty!")
        st.stop()

# 4.2) Fetch all schemes from MongoDB into a Python list
schemes_cursor = schemes_coll.find({})
all_schemes = list(schemes_cursor)

# 4.3) Build a list of scheme IDs for the dropdown
scheme_ids = [doc["scheme_id"] for doc in all_schemes]
if not scheme_ids:
    st.error("No schemes available in the database.")
    st.stop()


# =============================================================================
# 5) Select box for existing schemes
# =============================================================================
selected_id = st.selectbox("Select Scheme ID", scheme_ids)
if "new_scheme" in st.session_state:
    if selected_id != st.session_state["new_scheme"].get("scheme_id", ""):
        del st.session_state["new_scheme"]


# =============================================================================
# 6) Buttons for Adding or Deleting a Scheme
# =============================================================================
col1, col2 = st.columns(2)

with col1:
    if st.button("➕ Add New Scheme"):
        # Prepare a blank template
        blank_scheme = {
            "scheme_id": "",
            "jurisdiction": "",
            "scheme_name": "",
            "category": "",
            "status": "",
            "ministry": "",
            "target_group": "",
            "objective": "",
            "eligibility": "",
            "assistance": [],
            "key_benefits": "",
            "how_to_apply": "",
            "required_documents": [],
            "tags": "",
            "sources": "",
            "last_modified_by": None,
            "last_modified_at": None
        }
        st.session_state["new_scheme"] = blank_scheme

with col2:
    if st.button("🗑️ Delete This Scheme"):
        # Confirm deletion
        confirm = st.checkbox(f"Confirm deletion of '{selected_id}'", key="confirm_delete")
        if confirm:
            schemes_coll.delete_one({"scheme_id": selected_id})
            logs_coll.insert_one({
                "scheme_id": selected_id,
                "user": current_user,
                "action": "deleted",
                "timestamp": datetime.utcnow()
            })
            st.success(f"🗑️ Scheme '{selected_id}' deleted from MongoDB.")
            # Clear any stale state
            if "new_scheme" in st.session_state:
                del st.session_state["new_scheme"]


# =============================================================================
# 7) Determine whether we are editing an existing scheme or creating a new one
# =============================================================================
is_new = False
if "new_scheme" in st.session_state:
    scheme = st.session_state["new_scheme"]
    is_new = True
    st.subheader("🆕 Add New Scheme")
else:
    # Fetch the selected scheme from MongoDB
    scheme = schemes_coll.find_one({"scheme_id": selected_id})
    if not scheme:
        st.error(f"Scheme '{selected_id}' not found in the database.")
        st.stop()
    st.subheader(f"📝 Edit Scheme Details: {selected_id}")


# =============================================================================
# 8) If editing an existing scheme, attempt to acquire a lock
# =============================================================================
if not is_new:
    can_edit = acquire_lock(selected_id, current_user)
    if not can_edit:
        st.error("🚫 This scheme is currently being edited by someone else. Please try again later.")
        st.stop()


# =============================================================================
# 9) Show last update info for existing schemes
# =============================================================================
if not is_new:
    last_log = logs_coll.find_one(
        {"scheme_id": selected_id},
        sort=[("timestamp", -1)]
    )
    if last_log:
        last_user = last_log["user"]
        last_time = last_log["timestamp"].strftime("%Y-%m-%d %H:%M:%S")
        st.info(f"🕒 Last updated by **{last_user}** on **{last_time}**")
    else:
        st.info("ℹ️ This scheme has never been edited yet.")


# =============================================================================
# 10) Editable Form (for both new and existing schemes)
# =============================================================================
with st.form("edit_form"):
    # 10.1) scheme_id field
    if is_new:
        new_id = st.text_input("scheme_id", scheme.get("scheme_id", ""))
        scheme["scheme_id"] = new_id.strip()
    else:
        st.text_input("scheme_id", scheme["scheme_id"], disabled=True)

    # 10.2) All other fields
    for key, value in list(scheme.items()):
        if key == "scheme_id":
            continue
        if isinstance(value, list):
            new_val = st.text_area(key, "\n".join(value) if value else "")
            scheme[key] = [line.strip() for line in new_val.splitlines() if line.strip()]
        else:
            scheme[key] = st.text_area(key, value or "", height=100)

    submitted = st.form_submit_button("💾 Save Changes")

    if submitted:
        if is_new:
            # 10.3) Validation for a new scheme
            if not scheme["scheme_id"]:
                st.error("⚠️ scheme_id cannot be blank.")
            elif schemes_coll.find_one({"scheme_id": scheme["scheme_id"]}):
                st.error("⚠️ That scheme_id already exists. Choose a different one.")
            else:
                # Insert new scheme into MongoDB
                new_doc = scheme.copy()
                new_doc["last_modified_by"] = current_user
                new_doc["last_modified_at"] = datetime.utcnow()
                schemes_coll.insert_one(new_doc)
                logs_coll.insert_one({
                    "scheme_id": new_doc["scheme_id"],
                    "user": current_user,
                    "action": "created",
                    "timestamp": datetime.utcnow()
                })
                st.success(f"✅ New scheme '{new_doc['scheme_id']}' added to MongoDB.")
                # Clear session state so the next run is in "edit existing" mode
                del st.session_state["new_scheme"]
        else:
            # 10.4) Update existing scheme in MongoDB
            updated_doc = scheme.copy()
            updated_doc["last_modified_by"] = current_user
            updated_doc["last_modified_at"] = datetime.utcnow()
            if "_id" in updated_doc:
                updated_doc.pop("_id")
            schemes_coll.replace_one(
                {"scheme_id": selected_id},
                updated_doc
            )
            # Release the lock
            locks_coll.delete_one({"scheme_id": selected_id})
            # Log the edit
            logs_coll.insert_one({
                "scheme_id": selected_id,
                "user": current_user,
                "action": "edited",
                "timestamp": datetime.utcnow()
            })
            st.success("✅ Changes saved to MongoDB and lock released.")


# =============================================================================
# 11) Copy JSON Button (for the in-memory `scheme` dict)
# =============================================================================
scheme_json = json.dumps(scheme, indent=2, ensure_ascii=False)

st.subheader("📋 Copy Scheme JSON to Clipboard")
components.html(f"""
    <textarea id="schemeData" style="display:none;">{scheme_json}</textarea>
    <button onclick="navigator.clipboard.writeText(document.getElementById('schemeData').value); 
                     alert('Copied to clipboard!');">
        📋 Copy Scheme to Clipboard
    </button>
""", height=80)


# =============================================================================
# 12) Highlight Fields with Missing Information
# =============================================================================
st.subheader("🔍 Fields with Missing Information")
missing_keys = [
    k for k, v in scheme.items()
    if v in (None, [], "") and k != "scheme_id"
]
if missing_keys:
    st.warning(f"Missing fields: {', '.join(missing_keys)}")
else:
    st.success("All fields are filled ✅")
