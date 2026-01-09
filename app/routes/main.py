import os
import uuid
import mimetypes
import base64
import logging
import fitz  # PyMuPDF
import time
from flask import Blueprint, render_template, request, redirect, url_for, current_app, session, flash
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from app.utils import extract_text_with_gemini, evaluate_with_gemini
from app.models import db, AnswerScript 

main_bp = Blueprint('main', __name__)

@main_bp.route('/')
def welcome():
    return render_template('main/welcome.html')

@main_bp.route('/dashboard')
@login_required
def dashboard():
    return render_template('main/dashboard.html')

@main_bp.route('/upload', methods=['POST'])
@login_required
def upload_files():
    kb = request.files.get('knowledge_base')
    answers = request.files.getlist('answer_sheet')

    if not kb or not answers or answers[0].filename == '':
        flash("Please upload both knowledge base and at least one answer sheet.", "danger")
        return redirect(url_for('main.dashboard'))

    # Setup upload directory
    upload_id = uuid.uuid4().hex
    upload_folder = os.path.join(current_app.config['UPLOAD_FOLDER'], upload_id)
    os.makedirs(upload_folder, exist_ok=True)

    # 1. Process KB
    kb_filename = secure_filename(kb.filename)
    kb_path = os.path.join(upload_folder, kb_filename)
    kb.save(kb_path)
    
    # Extract KB Text
    kb_text = ""
    try:
        doc = fitz.open(kb_path)
        for page in doc:
            kb_text += page.get_text()
        doc.close()
    except Exception as e:
        logging.error(f"KB Extraction failed: {e}")
        flash("Failed to extract text from Knowledge Base PDF.", "warning")

    # 2. Process Answer Sheets
    pages_to_process = []
    local_extracted_text = [] # Store text extracted directly from digital PDFs
    
    # Save first answer file path for DB reference
    main_answer_path = "" 
    main_answer_filename = ""

    for file in answers:
        filename = secure_filename(file.filename)
        if not filename:
            continue
        
        file_path = os.path.join(upload_folder, filename)
        file.seek(0)
        file.save(file_path)

        if not main_answer_path:
            main_answer_path = f"uploads/{upload_id}/{filename}"
            main_answer_filename = filename

        mime_type = mimetypes.guess_type(filename)[0] or 'application/octet-stream'

        # Convert PDF pages to Images for OCR
        if filename.lower().endswith('.pdf'):
            try:
                doc = fitz.open(file_path)
                for page in doc:
                    # Hybrid Strategy: Try direct text extraction first
                    text = page.get_text().strip()
                    if len(text) > 50: # Threshold to ensure it's actual content
                        local_extracted_text.append(text)
                        continue

                    # If no text, use OCR
                    # Optimized: Matrix 1.0 (72 DPI) to reduce payload size and simulation usage
                    pix = page.get_pixmap(matrix=fitz.Matrix(1.0, 1.0))
                    data = pix.tobytes("jpeg", jpg_quality=80)
                    b64_img = base64.b64encode(data).decode('utf-8')
                    
                    pages_to_process.append({
                        "mime_type": "image/jpeg",
                        "data": b64_img
                    })
                doc.close()
            except Exception as e:
                logging.error(f"PDF Processing failed: {e}")
        
        # Handle Images
        elif mime_type.startswith('image'):
            try:
                with open(file_path, "rb") as f:
                    data = f.read()
                b64_img = base64.b64encode(data).decode('utf-8')
                
                pages_to_process.append({
                    "mime_type": mime_type,
                    "data": b64_img
                })
            except Exception as e:
                logging.error(f"Image Processing failed: {e}")

    # Batch Process all pages in ONE API call
    ocr_text = ""
    if pages_to_process:
        ocr_text = extract_text_with_gemini(pages_to_process)
    
    # Combine local text and OCR text
    final_student_text = "\n".join(local_extracted_text) + "\n" + ocr_text
    final_student_text = final_student_text.strip()
    
    if not final_student_text:
        final_student_text = "[Error: No readable pages found]"

    # 3. Save to Database
    new_script = AnswerScript(
        user_id=current_user.id,
        filename=main_answer_filename,
        file_path=main_answer_path,
        kb_text=kb_text,
        extracted_text=final_student_text
    )
    db.session.add(new_script)
    db.session.commit()

    return redirect(url_for('main.evaluate', script_id=new_script.id))

@main_bp.route('/evaluate/<int:script_id>')
@login_required
def evaluate(script_id):
    script = AnswerScript.query.get_or_404(script_id)
    
    # Ensure user owns this script
    if script.user_id != current_user.id and not current_user.is_admin:
        flash("You do not have permission to view this.", "danger")
        return redirect(url_for('main.dashboard'))

    # If not evaluated yet, do it now
    if not script.evaluation_json:
        evaluation_result = evaluate_with_gemini(script.kb_text, script.extracted_text)
        script.evaluation_json = evaluation_result
        db.session.commit()
    else:
        evaluation_result = script.evaluation_json

    # Simple mark extraction
    import re
    total_marks = "N/A"
    m = re.search(r"(?:Total\s*Marks)\s*[:=\-]?\s*([0-9/]+)", evaluation_result, re.I)
    if m:
        total_marks = m.group(1)

    return render_template(
        'main/evaluate.html',
        evaluation=evaluation_result,
        extracted_text=script.extracted_text,
        total_marks=total_marks,
        # kb_url=..., # Parsing URL from path if needed, but we focus on text now
        # answer_url=script.file_path, 
        preview_images=[] # Disabled for now to prevent cookie issues if we were passing them, but we aren't anymore.
    )
