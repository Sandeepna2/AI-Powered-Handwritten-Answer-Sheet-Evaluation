
import os
import re
import uuid
import base64
import logging
import sqlite3
from datetime import datetime
from io import BytesIO
import json
from functools import wraps

from dotenv import load_dotenv
from flask import (
    Flask, render_template, request,
    redirect, url_for, session, g, jsonify, make_response
)
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash

import fitz  # PyMuPDF
import requests
import mimetypes
import time
from google import genai
from google.genai import types

load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 40 * 1024 * 1024
app.config["SECRET_KEY"] = os.getenv("FLASK_SECRET_KEY", os.getenv("SECRET_KEY", "change-this-secret-key"))

DB_PATH = os.path.join(app.root_path, "static", "database", "users.db")
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

API_KEY = os.getenv("GOOGLE_API_KEY")

UPLOAD_ROOT = os.path.join(app.root_path, "static", "uploads")
os.makedirs(UPLOAD_ROOT, exist_ok=True)

# Per-upload temporary storage (keyed by upload_id)
upload_sessions = {}

# ==========================
# Database Helpers 
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
    db = get_db()
    db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            is_admin INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS evaluations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            student_name TEXT NOT NULL DEFAULT 'Unknown',
            kb_path TEXT,
            answer_path TEXT,
            extracted_text TEXT,
            evaluation_text TEXT,
            marks TEXT DEFAULT 'N/A',
            upload_id TEXT UNIQUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)
    db.commit()

    admin_email = "admin@example.com"
    admin_password = "admin123"
    cur = db.execute("SELECT id FROM users WHERE email = ?", (admin_email,))
    if cur.fetchone() is None:
        db.execute(
            "INSERT INTO users (email, password_hash, is_admin) VALUES (?, ?, ?)",
            (admin_email, generate_password_hash(admin_password), 1)
        )
        db.commit()
        logging.info("Default admin created: %s", admin_email)


@app.before_request
def setup():
    if not getattr(g, "_db_initialized", False):
        init_db()
        g._db_initialized = True

# ==========================
# Auth Helpers
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
            return render_template("errors/403.html"), 403
        return f(*args, **kwargs)
    return wrapper

# ==========================
# OCR & Gemini Helpers
# ==========================

def get_genai_client():
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise ValueError("GOOGLE_API_KEY environment variable is not configured.")
    return genai.Client(api_key=api_key)


FALLBACK_MODELS = ["gemini-2.0-flash", "gemini-2.5-flash", "gemini-2.0-flash-lite", "gemini-flash-latest"]

def call_gemini_api(contents, max_retries=3):
    """Call Gemini API via official google.genai SDK with model fallback and automatic retry on 429 rate limit."""
    client = get_genai_client()
    
    last_error = None
    for model_name in FALLBACK_MODELS:
        for attempt in range(max_retries):
            try:
                logging.info(f"Sending request to Gemini model: {model_name} (Attempt {attempt+1})")
                response = client.models.generate_content(
                    model=model_name,
                    contents=contents
                )
                if response and response.text:
                    return response.text.strip()
            except Exception as e:
                last_error = e
                err_str = str(e)
                if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str or "Quota" in err_str:
                    wait_time = (attempt + 1) * 3
                    logging.warning(f"Model {model_name} hit 429 Rate Limit (Attempt {attempt+1}/{max_retries}). Waiting {wait_time}s...")
                    time.sleep(wait_time)
                    continue
                else:
                    logging.error(f"Error with model {model_name}: {e}")
                    break  # Try next model in fallback list
        logging.warning(f"Model {model_name} quota limit reached. Switching to fallback model...")
    
    raise Exception(f"API Rate limit/quota exceeded across models. Details: {last_error}")


def extract_text_from_image_b64(img_b64: str, mime_type: str = "image/jpeg") -> str:
    """Send image bytes to google.genai SDK for handwriting extraction."""
    prompt = "Extract handwritten answer text from this image. Do not generate anything additional. Focus on accuracy and completeness."
    try:
        image_bytes = base64.b64decode(img_b64)
        image_part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
        contents = [prompt, image_part]
        return call_gemini_api(contents)
    except Exception as e:
        logging.exception("Error extracting text via Gemini SDK")
        return f"[Error extracting text: {e}]"


def extract_text_from_images_batch(image_list: list) -> str:
    """Batch process images using google.genai SDK in a single API call to prevent rate limiting."""
    if not image_list:
        return ""
    
    if len(image_list) == 1:
        return extract_text_from_image_b64(image_list[0]['b64'], image_list[0].get('mime_type', 'image/jpeg'))
    
    contents = [
        "Extract handwritten answer text from all provided pages in sequential order. Clearly demarcate each page with '--- Page Break ---'. Focus on accuracy and completeness."
    ]
    for img_item in image_list:
        image_bytes = base64.b64decode(img_item['b64'])
        mime_type = img_item.get('mime_type', 'image/jpeg')
        contents.append(types.Part.from_bytes(data=image_bytes, mime_type=mime_type))
        
    try:
        return call_gemini_api(contents)
    except Exception as e:
        if "429" in str(e):
            return "[Gemini API Rate Limit (429) reached. Please wait a few seconds and re-evaluate.]"
        return f"[Error extracting text: {e}]"


def extract_marks(evaluation_text, max_marks="100"):
    """Extract marks from evaluation text using multiple patterns."""
    patterns = [
        r"(?:Total\s*Marks|Score|Grade)\s*[:=\-]?\s*([0-9]+(?:\.[0-9]+)?(?:\s*/\s*[0-9]+)?)",
        r"(\d+(?:\.\d+)?)\s*(?:out of|/)\s*([0-9]+)",
        r"[Ss]core\s*[:=\-]?\s*(\d+(?:\.\d+)?)",
    ]
    for pattern in patterns:
        m = re.search(pattern, evaluation_text, re.I)
        if m:
            val = m.group(1)
            if "/" not in val and max_marks:
                return f"{val}/{max_marks}"
            return val
    return "N/A"

# ==========================
# Auth Routes
# ==========================

@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not email or not password:
            return render_template("signup.html", error="Email and password are required.")

        if len(password) < 6:
            return render_template("signup.html", error="Password must be at least 6 characters.")

        db = get_db()
        try:
            db.execute(
                "INSERT INTO users (email, password_hash) VALUES (?, ?)",
                (email, generate_password_hash(password))
            )
            db.commit()
        except sqlite3.IntegrityError:
            return render_template("signup.html", error="User already exists. Please login.")

        return redirect(url_for("login"))

    return render_template("signup.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not email or not password:
            return render_template("login.html", error="Email and password are required.")

        db = get_db()
        cur = db.execute("SELECT * FROM users WHERE email = ?", (email,))
        user = cur.fetchone()

        if user is None or not check_password_hash(user["password_hash"], password):
            return render_template("login.html", error="Invalid email or password")

        session["user_id"] = user["id"]
        session["email"] = user["email"]
        session["is_admin"] = bool(user["is_admin"])

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
    users = db.execute("SELECT id, email, is_admin, created_at FROM users").fetchall()
    return render_template("admin.html", users=users)

# ==========================
# Dashboard & History Routes
# ==========================

@app.route("/")
def welcome():
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    return render_template("welcome.html")

@app.route("/upload-form")
@login_required
def upload_form():
    return render_template("index.html")


@app.route("/dashboard")
@login_required
def dashboard():
    db = get_db()
    recent_evals = db.execute(
        """SELECT id, student_name, marks, created_at, evaluation_text
           FROM evaluations WHERE user_id = ?
           ORDER BY created_at DESC LIMIT 5""",
        (session["user_id"],)
    ).fetchall()

    total_evals = db.execute(
        "SELECT COUNT(*) as cnt FROM evaluations WHERE user_id = ?",
        (session["user_id"],)
    ).fetchone()["cnt"]

    eval_rows = db.execute(
        "SELECT marks FROM evaluations WHERE user_id = ? AND marks != 'N/A'",
        (session["user_id"],)
    ).fetchall()

    scores = []
    for r in eval_rows:
        m_str = r['marks']
        if '/' in m_str:
            try:
                parts = m_str.split('/')
                obtained = float(parts[0])
                tot = float(parts[1])
                if tot > 0:
                    scores.append((obtained / tot) * 100)
            except (ValueError, IndexError):
                pass

    avg_marks = f"{round(sum(scores) / len(scores), 1)}%" if scores else "N/A"

    return render_template("dashboard.html",
                           recent_evals=recent_evals,
                           total_evals=total_evals,
                           avg_marks=avg_marks)


@app.route("/history")
@login_required
def history():
    db = get_db()
    page = request.args.get('page', 1, type=int)
    query = request.args.get('q', '').strip()
    per_page = 10
    offset = (page - 1) * per_page

    if query:
        total = db.execute(
            "SELECT COUNT(*) as cnt FROM evaluations WHERE user_id = ? AND student_name LIKE ?",
            (session["user_id"], f"%{query}%")
        ).fetchone()["cnt"]

        evaluations = db.execute(
            """SELECT id, student_name, marks, created_at, evaluation_text
               FROM evaluations WHERE user_id = ? AND student_name LIKE ?
               ORDER BY created_at DESC LIMIT ? OFFSET ?""",
            (session["user_id"], f"%{query}%", per_page, offset)
        ).fetchall()
    else:
        total = db.execute(
            "SELECT COUNT(*) as cnt FROM evaluations WHERE user_id = ?",
            (session["user_id"],)
        ).fetchone()["cnt"]

        evaluations = db.execute(
            """SELECT id, student_name, marks, created_at, evaluation_text
               FROM evaluations WHERE user_id = ?
               ORDER BY created_at DESC LIMIT ? OFFSET ?""",
            (session["user_id"], per_page, offset)
        ).fetchall()

    total_pages = max(1, (total + per_page - 1) // per_page)

    return render_template("history.html",
                           evaluations=evaluations,
                           page=page,
                           total_pages=total_pages,
                           total=total,
                           query=query)


@app.route("/evaluation/<int:eval_id>")
@login_required
def view_evaluation(eval_id):
    db = get_db()
    evaluation = db.execute(
        """SELECT * FROM evaluations WHERE id = ? AND user_id = ?""",
        (eval_id, session["user_id"])
    ).fetchone()

    if not evaluation:
        return render_template("errors/404.html"), 404

    return render_template("evaluation_detail.html", evaluation=evaluation)


@app.route("/evaluation/<int:eval_id>/delete", methods=["POST"])
@login_required
def delete_evaluation(eval_id):
    db = get_db()
    db.execute(
        "DELETE FROM evaluations WHERE id = ? AND user_id = ?",
        (eval_id, session["user_id"])
    )
    db.commit()
    return redirect(url_for("history"))

@app.route("/api/detect-questions", methods=["POST"])
@login_required
def detect_questions():
    file = request.files.get('knowledge_base')
    if not file or not file.filename.lower().endswith('.pdf'):
        return jsonify({"error": "Please select a valid Question Paper PDF file."}), 400

    try:
        pdf_bytes = file.read()
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        qp_text = ""
        image_parts = []
        
        for page in doc:
            txt = page.get_text()
            qp_text += txt
            pix = page.get_pixmap(dpi=150)
            img_b = pix.tobytes("jpeg")
            image_parts.append(types.Part.from_bytes(data=img_b, mime_type="image/jpeg"))
        doc.close()

        prompt_str = """
Analyze this Question Paper and extract all question items.
Extract every question along with its exact question serial/number (e.g. 1, 2, 3, 4a, 4b), question title/description, and allocated marks.
Calculate the total maximum marks of the Question Paper.

Return strictly valid JSON with no markdown formatting around it, in this exact format:
{
  "total_marks": 50,
  "questions": [
    {"q_num": "1", "title": "Explain essentials of cohesive e-waste...", "marks": 10},
    {"q_num": "2", "title": "Illustrate e-waste flow...", "marks": 10}
  ]
}
"""
        if len(qp_text.strip()) > 50:
            contents = [f"{prompt_str}\n\nQuestion Paper Content:\n\"\"\"{qp_text[:6000]}\"\"\""]
        else:
            contents = [prompt_str] + image_parts[:3]

        response_text = call_gemini_api(contents)
        clean_json = re.sub(r"```(?:json)?\s*|\s*```", "", response_text).strip()
        data = json.loads(clean_json)
        return jsonify(data)
    except Exception as e:
        logging.exception("Auto-detection failed")
        return jsonify({"error": f"Detection failed: {str(e)}"}), 500


@app.route("/upload", methods=["POST"])
@login_required
def upload_files():
    kb = request.files.get('knowledge_base')
    answers = request.files.getlist('answer_sheet')
    student_name = request.form.get('student_name', 'Unknown').strip()
    total_marks = request.form.get('total_marks', '100').strip()
    marks_breakdown = request.form.get('marks_breakdown', '').strip()

    if not kb or not answers:
        return render_template("index.html", error="Please upload both Question Paper and at least one answer sheet.")

    if not kb.filename.lower().endswith('.pdf'):
        return render_template("index.html", error="Question paper must be a PDF file.")

    upload_id = uuid.uuid4().hex
    upload_folder = os.path.join(UPLOAD_ROOT, upload_id)
    os.makedirs(upload_folder, exist_ok=True)

    kb_filename = secure_filename(kb.filename)
    kb_full = os.path.join(upload_folder, kb_filename)
    kb.save(kb_full)
    kb_path = f"uploads/{upload_id}/{kb_filename}"

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

    images_to_extract = []
    all_preview_imgs = []
    answer_path = None

    for file in answers:
        filename = secure_filename(file.filename)
        if not filename:
            continue
        saved = os.path.join(upload_folder, filename)
        file.seek(0)
        file.save(saved)

        mime_type = getattr(file, "mimetype", None) or mimetypes.guess_type(filename)[0]

        if (mime_type == 'application/pdf') or filename.lower().endswith('.pdf'):
            if not answer_path:
                answer_path = f"uploads/{upload_id}/{filename}"
            try:
                doc = fitz.open(saved)
                for page in doc:
                    pix = page.get_pixmap(dpi=150)
                    img_bytes = pix.tobytes("jpeg")
                    b = base64.b64encode(img_bytes).decode("utf-8")
                    all_preview_imgs.append(b)
                    images_to_extract.append({'b64': b, 'mime_type': 'image/jpeg'})
                doc.close()
            except Exception:
                logging.exception("Failed PDF rendering with PyMuPDF")
                return render_template("index.html", error="Failed to process PDF file. Please ensure it is a valid PDF."), 500
        elif mime_type and mime_type.startswith("image"):
            try:
                with open(saved, "rb") as fh:
                    image_bytes = fh.read()
                b = base64.b64encode(image_bytes).decode("utf-8")
                all_preview_imgs.append(b)
                images_to_extract.append({'b64': b, 'mime_type': mime_type or 'image/jpeg'})
            except Exception:
                logging.exception("Failed to process image")
                continue

    extracted_text = extract_text_from_images_batch(images_to_extract)

    upload_sessions[upload_id] = {
        'kb_path': kb_path,
        'answer_path': answer_path,
        'kb_text': kb_text,
        'as_extracted_text': extracted_text,
        'as_preview_imgs': all_preview_imgs,
        'student_name': student_name,
        'total_marks': total_marks,
        'marks_breakdown': marks_breakdown,
        'user_id': session["user_id"]
    }

    # Cleanup old sessions (keep last 50)
    if len(upload_sessions) > 50:
        oldest_keys = list(upload_sessions.keys())[:-50]
        for k in oldest_keys:
            upload_sessions.pop(k, None)

    return redirect(url_for("evaluate", uid=upload_id))


@app.route("/evaluate")
@login_required
def evaluate():
    upload_id = request.args.get("uid")
    if not upload_id or upload_id not in upload_sessions:
        return redirect(url_for("dashboard"))

    data = upload_sessions[upload_id]

    if data['user_id'] != session["user_id"]:
        return redirect(url_for("dashboard"))

    # Pause briefly to prevent hitting Gemini API 429 rate limit between OCR and evaluation calls
    time.sleep(1.5)

    truncated_kb = data.get('kb_text', "")[:4000]
    student_answer = data.get('as_extracted_text', "")
    total_marks = data.get('total_marks', '100')
    marks_breakdown = data.get('marks_breakdown', '')

    breakdown_section = f"\nSpecified Question-wise Marks Allocation:\n{marks_breakdown}\n" if marks_breakdown else ""

    prompt = f"""
You are a professional examiner evaluating handwritten student answers against the Question Paper.

Question Paper:
\"\"\"{truncated_kb}\"\"\"

Student Answer:
\"\"\"{student_answer}\"\"\"

Evaluation Settings & Total Marks:
- Total Maximum Marks for this Exam: {total_marks}
{breakdown_section}

Please evaluate question by question and return clean markdown formatting:

### 1. Question-wise Marks Breakdown

Format EACH question inside a card block using exact markdown headers like this:

#### Question Q1
- **Allocated Marks**: [Allocated]
- **Obtained Marks**: [Obtained]
- **Feedback**: [Detailed feedback explaining deductions]

#### Question Q2
- **Allocated Marks**: [Allocated]
- **Obtained Marks**: [Obtained]
- **Feedback**: [Detailed feedback]

### 2. Final Results Summary
- **Total Marks**: [Obtained Total] / {total_marks}
- **Relevance Score**: [Score / 5]
- **Accuracy Score**: [Score / 5]
- **Key Missing Points**: [Bullet list]
- **Suggestions for Improvement**: [Bullet list]
- **One-line Summary Feedback**: [Summary]
"""
    try:
        evaluation = call_gemini_api([prompt])
    except Exception as e:
        logging.exception("Evaluation API failed via Gemini SDK")
        evaluation = f"[Error calling evaluation API: {e}]"

    marks = extract_marks(evaluation, max_marks=total_marks)

    db = get_db()
    try:
        db.execute(
            """INSERT INTO evaluations
               (user_id, student_name, kb_path, answer_path, extracted_text, evaluation_text, marks, upload_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (session["user_id"], data.get('student_name', 'Unknown'),
             data.get('kb_path'), data.get('answer_path'),
             data.get('as_extracted_text', ''), evaluation, marks, upload_id)
        )
        db.commit()
    except sqlite3.Error:
        logging.exception("Failed to save evaluation to database")

    upload_sessions.pop(upload_id, None)

    return render_template(
        "evaluate.html",
        kb_path=data.get('kb_path'),
        answer_path=data.get('answer_path'),
        extracted_text=data.get('as_extracted_text', ""),
        image_data_list=data.get('as_preview_imgs', []),
        evaluation=evaluation,
        marks=marks,
        student_name=data.get('student_name', 'Unknown'),
        upload_id=upload_id
    )


@app.route("/download/<int:eval_id>")
@login_required
def download_report(eval_id):
    db = get_db()
    evaluation = db.execute(
        "SELECT * FROM evaluations WHERE id = ? AND user_id = ?",
        (eval_id, session["user_id"])
    ).fetchone()

    if not evaluation:
        return render_template("errors/404.html"), 404

    report_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Evaluation Report - {evaluation['student_name']}</title>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap');
        body {{ font-family: 'Inter', sans-serif; margin: 0; padding: 40px; color: #1e293b; background: #fff; line-height: 1.6; }}
        .header {{ display: flex; justify-content: space-between; align-items: center; border-bottom: 2px solid #4f46e5; padding-bottom: 15px; margin-bottom: 25px; }}
        .brand {{ font-size: 24px; font-weight: 800; color: #4f46e5; }}
        .badge {{ background: #dcfce7; color: #166534; padding: 8px 18px; border-radius: 20px; font-size: 18px; font-weight: 700; border: 1px solid #a7f3d0; }}
        .meta-card {{ background: #f8fafc; border: 1px solid #e2e8f0; padding: 20px; border-radius: 12px; margin-bottom: 25px; display: grid; grid-template-columns: repeat(3, 1fr); gap: 15px; }}
        .meta-item {{ font-size: 14px; }}
        .meta-item label {{ display: block; color: #64748b; font-size: 12px; font-weight: 600; text-transform: uppercase; margin-bottom: 3px; }}
        .meta-item value {{ font-weight: 700; color: #0f172a; font-size: 16px; }}
        h2 {{ color: #4f46e5; font-size: 18px; border-left: 4px solid #4f46e5; padding-left: 10px; margin-top: 30px; margin-bottom: 15px; }}
        .content-box {{ background: #f9fafb; border: 1px solid #e2e8f0; padding: 20px; border-radius: 10px; white-space: pre-wrap; font-size: 14px; line-height: 1.6; }}
        .footer {{ margin-top: 50px; padding-top: 20px; border-top: 1px solid #e2e8f0; text-align: center; color: #94a3b8; font-size: 12px; }}
        @media print {{ body {{ padding: 0; }} }}
    </style>
</head>
<body>
    <div class="header">
        <div class="brand">Bluebook Corrector</div>
        <div class="badge">Score: {evaluation['marks']}</div>
    </div>
    
    <div class="meta-card">
        <div class="meta-item">
            <label>Student Name</label>
            <value>{evaluation['student_name']}</value>
        </div>
        <div class="meta-item">
            <label>Evaluation Date</label>
            <value>{evaluation['created_at']}</value>
        </div>
        <div class="meta-item">
            <label>Status</label>
            <value>Completed</value>
        </div>
    </div>

    <h2>AI Evaluation & Rubric Feedback</h2>
    <div class="content-box">{evaluation['evaluation_text']}</div>

    <h2>Extracted Handwriting OCR Text</h2>
    <div class="content-box">{evaluation['extracted_text'] if evaluation['extracted_text'] else 'No text extracted.'}</div>

    <div class="footer">
        Generated automatically by Bluebook Corrector - AI-Powered Answer Sheet Evaluation System
    </div>
</body>
</html>"""

    response = make_response(report_html)
    response.headers['Content-Type'] = 'text/html'
    response.headers['Content-Disposition'] = f'attachment; filename=evaluation_{eval_id}.html'
    return response


@app.errorhandler(404)
def not_found(e):
    return render_template("errors/404.html"), 404


@app.errorhandler(413)
def too_large(e):
    return render_template("errors/413.html"), 413


@app.errorhandler(500)
def server_error(e):
    return render_template("errors/500.html"), 500


if __name__ == "__main__":
    app.run(debug=True)
