# Automated Answer Script Evaluation System

An AI-powered system to automate the grading of handwritten answer sheets using Google's Gemini 2.0 Flash API.

## Features
- **Smart OCR**: Extracts handwritten text from images with high accuracy.
- **AI Grading**: specific evaluation with scores, feedback, and corrections.
- **Dashboard**: Track uploads and view detailed reports.
- **Secure**: User authentication and role-based access.

## Setup

1.  **Install Prerequisites**
    ```bash
    pip install -r requirements.txt
    ```

2.  **Configuration**
    - Rename `.env.example` to `.env`
    - Add your API Key: `GEMINI_API_KEY=your_key_here`

3.  **Run the Application**
    ```bash
    python app.py
    ```

4.  **Usage**
    - Open `http://127.0.0.1:5000`
    - Register a new account.
    - Upload an image of an answer script.
    - Wait a few seconds for the AI to analyze and grade it.

## Tech Stack
- **Backend**: Flask, SQLAlchemy
- **AI**: Gemini 2.0 Flash (REST API)
- **Frontend**: HTML5, CSS3, JavaScript
