# AI-Powered Handwritten Answer Sheet Evaluation
## Bluebook Corrector – Automated Exam Assessment Using OCR, NLP, and LLMs 



## Overview
Bluebook Corrector is an AI-powered system designed to automatically evaluate handwritten examination answer sheets.

It uses:
- OCR (Optical Character Recognition)
- NLP (Natural Language Processing)
- LLM-based evaluation (Google Gemini API)
- PDF to image extraction (Poppler)

The system provides:
- Extracted student answers
- Comparison with knowledge base
- Automatic scoring
- Missing points and feedback
- Visual preview of pages

---

## Project Highlights

| Feature | Description |
|--------|-------------|
| Upload KB + Answer Sheet | Supports PDF, PNG, JPG |
| Smart OCR | Extracts clean text from handwritten answers |
| AI Evaluation | Uses Gemini to analyze relevance and key points |
| Auto Scoring | Assigns marks intelligently |
| PDF Page Preview | Shows page previews for each answer sheet |
| Authentication | Login, Signup, Logout (SQLite + Flask) |
| Admin Panel | View registered users |
| Auto File Management | Saves uploads in per-session folders |

---

## Tech Stack

### Frontend
- HTML5  
- CSS3  
- Responsive UI  
- Navbar, Dashboard, Authentication Pages  

### Backend
- Flask (Python)  
- SQLite Database  
- Poppler (PDF rendering)  
- PyMuPDF (KB extraction)  
- Requests (Gemini API calls)

### AI Components
- Google Gemini 2.0 Flash API  
- OCR + NLP  
- Semantic evaluation

---

## Project Structure

```
project/
│── app.py
│── requirements.txt
│── .env
│
├── templates/
│   ├── welcome.html
│   ├── login.html
│   ├── signup.html
│   ├── index.html
│   ├── evaluate.html
│   ├── admin.html
│   └── navbar.html
│
├── static/
│   ├── uploads/
│   └── database/
│       └── users.db
```

---

## Setup Instructions

### 1. Clone the Project
```
git clone https://github.com/your-username/bluebook-corrector.git
cd bluebook-corrector
```

### 2. Create Virtual Environment
```
python -m venv venv
venv\Scripts\activate
```

### 3. Install Requirements
```
pip install -r requirements.txt
```

### 4. Install Poppler (Windows)
Download Poppler from:
https://github.com/oschwartz10612/poppler-windows/releases/

Add path to `.env`:
```
POPPLER_PATH=C:\path\to\poppler\Library\bin
```

### 5. Add Gemini API Key to `.env`
```
GOOGLE_API_KEY=your_api_key_here
SECRET_KEY=your_flask_secret
```

---

## Running the Application
```
python app.py
```

Open in browser:
http://127.0.0.1:5000/

---

## Authentication Features
- Secure signup  
- Password hashing (Werkzeug)  
- Session-based authentication  
- Admin user support  
- SQLite database storage  

---

## AI Evaluation Workflow
1. Upload knowledge base PDF  
2. Upload answer sheet (PDF/Images)  
3. Convert PDF to images  
4. Extract text using Gemini OCR  
5. Compare answer with KB using LLM  
6. AI generates:  
   - Marks  
   - Relevance  
   - Accuracy  
   - Missing points  
   - Final feedback  

Results appear in `evaluate.html`.

---

## UI Features
- Clean and simple UI  
- Fixed navigation bar  
- Gradient backgrounds for login and signup  
- Dashboard interface  
- Evaluation preview grid layout  

---



## Author
**Sandeep N A**  
B.E. Computer Science and Engineering  
CMR Institute of Technology  
Aspiring Software Developer | AI & Web Technologies



