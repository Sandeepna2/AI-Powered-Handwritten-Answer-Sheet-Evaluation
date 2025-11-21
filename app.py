# import os
# import re
# import uuid
# import base64
# import logging
# from io import BytesIO
# from dotenv import load_dotenv
# from flask import Flask, render_template, request, redirect, url_for   
# from werkzeug.utils import secure_filename                             

# # image/pdf libs                                                       
# from pdf2image import convert_from_bytes
# try:
#     import fitz  # PyMuPDF
# except Exception:
#     fitz = None

# import requests
# import mimetypes

# # Load .env
# load_dotenv()
# logging.basicConfig(level=logging.INFO)

# app = Flask(__name__)
# app.config['MAX_CONTENT_LENGTH'] = 40 * 1024 * 1024  # 40 MB max

# # Config
# API_KEY = os.getenv("GOOGLE_API_KEY")
# GEMINI_ENDPOINT = os.getenv(
#     "GEMINI_ENDPOINT",
#     "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"
# ) 
# POPPLER_PATH = os.getenv( 
#     "POPPLER_PATH",
#     r"C:\Users\Admin\Downloads\Release-25.07.0-0\poppler-25.07.0\Library\bin"
# )

# # Always save files inside static/uploads
# UPLOAD_ROOT = os.path.join(app.root_path, "static", "uploads")
# os.makedirs(UPLOAD_ROOT, exist_ok=True)

# # Global state
# state = {
#     'kb_path': None,
#     'as_path': None,
#     'kb_text': "",
#     'as_extracted_text': "",
#     'as_preview_imgs': [],
#     'total_marks': "N/A"
# }


# def extract_text_from_image_b64(img_b64: str, mime_type: str = "image/jpeg") -> str:
#     """Send base64 image to Gemini endpoint for handwriting extraction."""
#     prompt = "Extract handwritten answer text from this image. Do not generate anything additional. Focus on accuracy and completeness."
#     request_body = {
#         "contents": [
#             {
#                 "parts": [
#                     {"text": prompt},
#                     {"inlineData": {"mimeType": mime_type, "data": img_b64}}
#                 ]
#             }
#         ]
#     }
#     try:
#         resp = requests.post(f"{GEMINI_ENDPOINT}?key={API_KEY}", json=request_body, timeout=30)
#         resp.raise_for_status()
#         data = resp.json()

#         candidates = data.get("candidates", [])
#         if candidates and "content" in candidates[0]:
#             parts = candidates[0]["content"].get("parts", [])
#             if parts and "text" in parts[0]:
#                 return parts[0]["text"].strip()
#         return "[Error: No text in Gemini response]"
#     except Exception as e:
#         logging.exception("Error calling Gemini OCR API")
#         return f"[Error extracting text: {e}]"


# @app.route("/")
# def index():
#     return render_template("index.html")


# @app.route("/upload", methods=["POST"])
# def upload_files():
#     kb = request.files.get('knowledge_base')
#     answers = request.files.getlist('answer_sheet')

#     if not kb or not answers:
#         return "Please upload both knowledge base and at least one answer sheet.", 400

#     # unique folder for each upload
#     upload_id = uuid.uuid4().hex
#     upload_folder = os.path.join(UPLOAD_ROOT, upload_id)
#     os.makedirs(upload_folder, exist_ok=True)

#     # Save KB file
#     kb_filename = secure_filename(kb.filename)
#     kb_full = os.path.join(upload_folder, kb_filename)
#     kb.save(kb_full)

#     # Store relative path (Flask will serve from static/)
#     state['kb_path'] = f"uploads/{upload_id}/{kb_filename}"

#     # Extract KB text if PyMuPDF available
#     kb_text = ""
#     if fitz:
#         try:
#             doc = fitz.open(kb_full)
#             for page in doc:
#                 kb_text += page.get_text()
#             doc.close()
#         except Exception:
#             logging.exception("PyMuPDF failed to extract KB text")
#     else:
#         logging.warning("PyMuPDF not available; skipping KB text extraction")
#     state['kb_text'] = kb_text

#     # Process answers
#     all_extracted = []
#     all_preview_imgs = []

#     for file in answers:
#         filename = secure_filename(file.filename)
#         if not filename:
#             continue
#         saved = os.path.join(upload_folder, filename)
#         file.seek(0)
#         file.save(saved)

#         mime_type = getattr(file, "mimetype", None) or mimetypes.guess_type(filename)[0]

#         if (mime_type == 'application/pdf') or filename.lower().endswith('.pdf'):
#             try:
#                 with open(saved, "rb") as fh:
#                     pdf_bytes = fh.read()
#                 images = convert_from_bytes(pdf_bytes, dpi=200, poppler_path=POPPLER_PATH)
#                 for image in images:
#                     buf = BytesIO()
#                     image.save(buf, format="JPEG")
#                     b = base64.b64encode(buf.getvalue()).decode("utf-8")
#                     all_preview_imgs.append(b)
#                     all_extracted.append(extract_text_from_image_b64(b, mime_type="image/jpeg"))
#             except Exception:
#                 logging.exception("Failed PDF -> images")
#                 return "PDF to image conversion failed; ensure Poppler is installed and POPPLER_PATH is correct.", 500
#         elif mime_type and mime_type.startswith("image"):
#             try:
#                 with open(saved, "rb") as fh:
#                     image_bytes = fh.read()
#                 b = base64.b64encode(image_bytes).decode("utf-8")
#                 all_preview_imgs.append(b)
#                 all_extracted.append(extract_text_from_image_b64(b, mime_type=mime_type or "image/jpeg"))
#             except Exception:
#                 logging.exception("Failed to process image")
#                 continue

#     state['as_extracted_text'] = "\n\n--- Page Break ---\n\n".join(all_extracted)
#     state['as_preview_imgs'] = all_preview_imgs

#     # Save first answer PDF path for preview                                                                                                                              
#     for file in answers:
#         if file.filename.lower().endswith(".pdf"):
#             state['as_path'] = f"uploads/{upload_id}/{secure_filename(file.filename)}"
#             break

#     return redirect(url_for("evaluate"))


# @app.route("/evaluate")
# def evaluate():
#     truncated_kb = state.get('kb_text', "")[:4000]  # allow longer KB
#     student_answer = state.get('as_extracted_text', "")

#     prompt = f"""
# You are a professional examiner evaluating handwritten student answers.    

# Knowledge Base:
# \"\"\"{truncated_kb}\"\"\"

# Student Answer:
# \"\"\"{student_answer}\"\"\"

# Please evaluate and return the result in the following clear format:

# Analyze thoroughly and provide:
# - Total Marks (out of 10)
# - Relevance
# - Accuracy
# - Missing Key Points
# - Suggestions
# - One-line summary feedback
# """ 
#     request_body = {"contents": [{"parts": [{"text": prompt}]}]}

#     try:
#         resp = requests.post(f"{GEMINI_ENDPOINT}?key={API_KEY}", json=request_body, timeout=30)
#         resp.raise_for_status()
#         data = resp.json()

#         candidates = data.get("candidates", [])
#         if candidates and "content" in candidates[0]:
#             parts = candidates[0]["content"].get("parts", [])
#             if parts and "text" in parts[0]:
#                 evaluation = parts[0]["text"]
#             else:
#                 evaluation = "[No evaluation text found]"
#         else: 
#             evaluation = "[No candidates returned]"
#     except Exception:
#         logging.exception("Evaluation API failed")
#         evaluation = "[Error calling evaluation API]"

#     # --- Extract marks safely ---                      
#     marks = "N/A"
#     question = "N/A"
#     m = re.search(r"(?:Total\s*Marks|Marks\s*Awarded|Score)\s*[:=\-]?\s*([0-9]+(?:\.[0-9]+)?(?:\s*/\s*[0-9]+)?)", evaluation, re.I)
#     if m:
#         marks = m.group(1)

#     state['total_marks'] = marks  # ✅ Save in global state   

#     return render_template("evaluate.html",
#                            kb_path=state.get('kb_path'),
#                            answer_path=state.get('as_path'),
#                            extracted_text=state.get('as_extracted_text', ""),
#                            image_data_list=state.get('as_preview_imgs', []),
#                            evaluation=evaluation,
#                            marks=marks,
#                            question=question,
#                            total_marks=state.get('total_marks'))

# if __name__ == "__main__":
#     app.run(debug=True)

import os
import re
import uuid
import base64
import logging
import sqlite3
from io import BytesIO
from functools import wraps

from dotenv import load_dotenv
from flask import (
    Flask, render_template, request,
    redirect, url_for, session, g
)
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash

# image/pdf libs
from pdf2image import convert_from_bytes
try:
    import fitz  # PyMuPDF
except Exception:
    fitz = None

import requests
import mimetypes

# Load .env
load_dotenv()
logging.basicConfig(level=logging.INFO)

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 40 * 1024 * 1024  # 40 MB max

# 🔐 Secret key for sessions
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "change-this-secret-key")

# 📦 SQLite DB path → static/database/users.db
DB_PATH = os.path.join(app.root_path, "static", "database", "users.db")
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

# Config
API_KEY = os.getenv("GOOGLE_API_KEY")
GEMINI_ENDPOINT = os.getenv(
    "GEMINI_ENDPOINT",
    "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"
)
POPPLER_PATH = os.getenv(
    "POPPLER_PATH",
    r"C:\Users\Admin\Downloads\Release-25.07.0-0\poppler-25.07.0\Library\bin"
)

# Always save files inside static/uploads
UPLOAD_ROOT = os.path.join(app.root_path, "static", "uploads")
os.makedirs(UPLOAD_ROOT, exist_ok=True)

# Global state
state = {
    'kb_path': None,
    'as_path': None,
    'kb_text': "",
    'as_extracted_text': "",
    'as_preview_imgs': [],
    'total_marks': "N/A"
}

# ==========================
# 🔹 Database Helpers
# ==========================

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exception=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    """Create users table + default admin if not exists."""
    db = get_db()
    db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            is_admin INTEGER DEFAULT 0
        )
    """)
    db.commit()

    # Default admin user
    admin_email = "admin@example.com"
    admin_password = "admin123"   # 👉 change later in production
    cur = db.execute("SELECT id FROM users WHERE email = ?", (admin_email,))
    if cur.fetchone() is None:
        db.execute(
            "INSERT INTO users (email, password_hash, is_admin) VALUES (?, ?, ?)",
            (admin_email, generate_password_hash(admin_password), 1)
        )
        db.commit()
        logging.info(f"Default admin created: {admin_email} / {admin_password}")


# Flask 3: use before_request instead of before_first_request
@app.before_request
def setup():
    if not getattr(g, "_db_initialized", False):
        init_db()
        g._db_initialized = True

# ==========================
# 🔹 Auth Helpers
# ==========================

def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper


def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "user_id" not in session or not session.get("is_admin"):
            return "Access denied: Admins only", 403
        return f(*args, **kwargs)
    return wrapper

# ==========================
# 🔹 OCR Helper (your original)
# ==========================

def extract_text_from_image_b64(img_b64: str, mime_type: str = "image/jpeg") -> str:
    """Send base64 image to Gemini endpoint for handwriting extraction."""
    prompt = "Extract handwritten answer text from this image. Do not generate anything additional. Focus on accuracy and completeness."
    request_body = {
        "contents": [
            {
                "parts": [
                    {"text": prompt},
                    {"inlineData": {"mimeType": mime_type, "data": img_b64}}
                ]
            }
        ]
    }
    try:
        resp = requests.post(f"{GEMINI_ENDPOINT}?key={API_KEY}", json=request_body, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        candidates = data.get("candidates", [])
        if candidates and "content" in candidates[0]:
            parts = candidates[0]["content"].get("parts", [])
            if parts and "text" in parts[0]:
                return parts[0]["text"].strip()
        return "[Error: No text in Gemini response]"
    except Exception as e:
        logging.exception("Error calling Gemini OCR API")
        return f"[Error extracting text: {e}]"

# ==========================
# 🔹 Auth Routes
# ==========================

@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not email or not password:
            return "Email and password are required."

        db = get_db()
        try:
            db.execute(
                "INSERT INTO users (email, password_hash) VALUES (?, ?)",
                (email, generate_password_hash(password))
            )
            db.commit()
        except sqlite3.IntegrityError:
            return "User already exists. Please login."

        return redirect(url_for("login"))

    return render_template("signup.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        db = get_db()
        cur = db.execute("SELECT * FROM users WHERE email = ?", (email,))
        user = cur.fetchone()

        if user is None or not check_password_hash(user["password_hash"], password):
            return "Invalid email or password"

        session["user_id"] = user["id"]
        session["email"] = user["email"]
        session["is_admin"] = bool(user["is_admin"])

        # After login → go to dashboard
        return redirect(url_for("dashboard"))

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/admin")
@admin_required
def admin_dashboard():
    db = get_db()
    users = db.execute("SELECT id, email, is_admin FROM users").fetchall()
    return render_template("admin.html", users=users)

# ==========================
# 🔹 App Routes (welcome + dashboard + evaluation)
# ==========================

# Public welcome page
@app.route("/")
def welcome():
    return render_template("welcome.html")


# Dashboard = your old index.html (upload page) – protected
@app.route("/dashboard")
@login_required
def dashboard():
    return render_template("index.html")


@app.route("/upload", methods=["POST"])
@login_required
def upload_files():
    kb = request.files.get('knowledge_base')
    answers = request.files.getlist('answer_sheet')

    if not kb or not answers:
        return "Please upload both knowledge base and at least one answer sheet.", 400

    # unique folder for each upload
    upload_id = uuid.uuid4().hex
    upload_folder = os.path.join(UPLOAD_ROOT, upload_id)
    os.makedirs(upload_folder, exist_ok=True)

    # Save KB file
    kb_filename = secure_filename(kb.filename)
    kb_full = os.path.join(upload_folder, kb_filename)
    kb.save(kb_full)

    # Store relative path (Flask will serve from static/)
    state['kb_path'] = f"uploads/{upload_id}/{kb_filename}"

    # Extract KB text if PyMuPDF available
    kb_text = ""
    if fitz:
        try:
            doc = fitz.open(kb_full)
            for page in doc:
                kb_text += page.get_text()
            doc.close()
        except Exception:
            logging.exception("PyMuPDF failed to extract KB text")
    else:
        logging.warning("PyMuPDF not available; skipping KB text extraction")
    state['kb_text'] = kb_text

    # Process answers
    all_extracted = []
    all_preview_imgs = []

    for file in answers:
        filename = secure_filename(file.filename)
        if not filename:
            continue
        saved = os.path.join(upload_folder, filename)
        file.seek(0)
        file.save(saved)

        mime_type = getattr(file, "mimetype", None) or mimetypes.guess_type(filename)[0]

        if (mime_type == 'application/pdf') or filename.lower().endswith('.pdf'):
            try:
                with open(saved, "rb") as fh:
                    pdf_bytes = fh.read()
                images = convert_from_bytes(pdf_bytes, dpi=200, poppler_path=POPPLER_PATH)
                for image in images:
                    buf = BytesIO()
                    image.save(buf, format="JPEG")
                    b = base64.b64encode(buf.getvalue()).decode("utf-8")
                    all_preview_imgs.append(b)
                    all_extracted.append(extract_text_from_image_b64(b, mime_type="image/jpeg"))
            except Exception:
                logging.exception("Failed PDF -> images")
                return "PDF to image conversion failed; ensure Poppler is installed and POPPLER_PATH is correct.", 500
        elif mime_type and mime_type.startswith("image"):
            try:
                with open(saved, "rb") as fh:
                    image_bytes = fh.read()
                b = base64.b64encode(image_bytes).decode("utf-8")
                all_preview_imgs.append(b)
                all_extracted.append(extract_text_from_image_b64(b, mime_type=mime_type or "image/jpeg"))
            except Exception:
                logging.exception("Failed to process image")
                continue

    state['as_extracted_text'] = "\n\n--- Page Break ---\n\n".join(all_extracted)
    state['as_preview_imgs'] = all_preview_imgs

    # Save first answer PDF path for preview
    for file in answers:
        if file.filename.lower().endswith(".pdf"):
            state['as_path'] = f"uploads/{upload_id}/{secure_filename(file.filename)}"
            break

    return redirect(url_for("evaluate"))


@app.route("/evaluate")
@login_required
def evaluate():
    truncated_kb = state.get('kb_text', "")[:4000]  # allow longer KB
    student_answer = state.get('as_extracted_text', "")

    prompt = f"""
You are a professional examiner evaluating handwritten student answers.    

Knowledge Base:
\"\"\"{truncated_kb}\"\"\"


Student Answer:
\"\"\"{student_answer}\"\"\"


Please evaluate and return the result in the following clear format:

Analyze thoroughly and provide:
- Total Marks (out of 10)
- Relevance
- Accuracy
- Missing Key Points
- Suggestions
- One-line summary feedback
"""
    request_body = {"contents": [{"parts": [{"text": prompt}]}]}

    try:
        resp = requests.post(f"{GEMINI_ENDPOINT}?key={API_KEY}", json=request_body, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        candidates = data.get("candidates", [])
        if candidates and "content" in candidates[0]:
            parts = candidates[0]["content"].get("parts", [])
            if parts and "text" in parts[0]:
                evaluation = parts[0]["text"]
            else:
                evaluation = "[No evaluation text found]"
        else:
            evaluation = "[No candidates returned]"
    except Exception:
        logging.exception("Evaluation API failed")
        evaluation = "[Error calling evaluation API]"

    # --- Extract marks safely ---
    marks = "N/A"
    question = "N/A"
    m = re.search(
        r"(?:Total\s*Marks|Marks\s*Awarded|Score)\s*[:=\-]?\s*([0-9]+(?:\.[0-9]+)?(?:\s*/\s*[0-9]+)?)",
        evaluation,
        re.I
    )
    if m:
        marks = m.group(1)

    state['total_marks'] = marks  # Save in global state

    return render_template(
        "evaluate.html",
        kb_path=state.get('kb_path'),
        answer_path=state.get('as_path'),
        extracted_text=state.get('as_extracted_text', ""),
        image_data_list=state.get('as_preview_imgs', []),
        evaluation=evaluation,
        marks=marks,
        question=question,
        total_marks=state.get('total_marks')
    )


if __name__ == "__main__":
    app.run(debug=True)
