# backend/firebase_admin_config.py
import os
import json
import tempfile
import firebase_admin
from firebase_admin import credentials, firestore

# Name of the env var we will use to store the service account JSON
SERVICE_ACCOUNT_ENV = "SERVICE_ACCOUNT_JSON"
# Local fallback filename (ignored by git)
LOCAL_KEYFILE = os.path.join(os.path.dirname(__file__), "serviceAccountKey.json")

def _write_temp_keyfile(json_str: str):
    """
    Write the JSON string to a temp file and return the path.
    We use tempfile to avoid leaving secrets in repo.
    """
    fd, path = tempfile.mkstemp(prefix="svcacct_", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(json_str)
    return path

def _load_service_account_path():
    # 1) Preferred: load full JSON from env var (set on Render)
    sa_json = os.environ.get(SERVICE_ACCOUNT_ENV)
    if sa_json:
        # If it's stored base64-encoded, user can decode before setting; here we assume raw JSON
        try:
            # validate JSON
            json.loads(sa_json)
        except Exception:
            raise RuntimeError(f"{SERVICE_ACCOUNT_ENV} is set but not valid JSON")

        return _write_temp_keyfile(sa_json)

    # 2) Fallback: local file path (useful while developing locally)
    if os.path.exists(LOCAL_KEYFILE):
        return LOCAL_KEYFILE

    # Not found
    return None

KEY_PATH = _load_service_account_path()

if not KEY_PATH:
    # Strong, explicit error to help detect missing secret early
    raise RuntimeError(
        "Firebase service account not found. "
        f"Set {SERVICE_ACCOUNT_ENV} environment variable (with JSON) or place "
        f"{LOCAL_KEYFILE} locally for development."
    )

if not firebase_admin._apps:
    cred = credentials.Certificate(KEY_PATH)
    firebase_admin.initialize_app(cred)

db = firestore.client()
