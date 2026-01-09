
import time
import os
import requests
import json
import logging
from flask import current_app

def extract_text_with_gemini(pages_data):
    """
    Extracts handwritten text using ROBUST CHUNKING.
    - Processes pages in groups of 3 (Balanced Speed vs Reliability).
    - Includes SOFT FALLBACK: If a chunk fails, it yields a placeholder instead of crashing.
    """
    api_key = current_app.config.get('GEMINI_API_KEY')
    endpoint = current_app.config.get('GEMINI_ENDPOINT')
    
    if not api_key: return "[Error: API Key missing]"
    if not pages_data: return ""

    logging.info(f"--- Starting Robust Chunking Extraction for {len(pages_data)} pages ---")
    
    # Chunk size of 3 is a sweet spot for Gemini Flash (approx 3-4 images per call is safe)
    CHUNK_SIZE = 3
    all_extracted_text = []

    for i in range(0, len(pages_data), CHUNK_SIZE):
        chunk = pages_data[i : i + CHUNK_SIZE]
        chunk_index = (i // CHUNK_SIZE) + 1
        logging.info(f"Processing Chunk {chunk_index} (Pages {i+1}-{i+len(chunk)})...")

        prompt = "Extract text from these images sequentially. Return text only."
        parts = [{"text": prompt}]
        for  page in chunk:
            parts.append({
                "inlineData": {
                    "mimeType": page["mime_type"],
                    "data": page["data"]
                }
            })
        
        payload = {"contents": [{"parts": parts}]}
        
        # Retry Logic for Chunk
        chunk_text = f"[Error: Could not extract text from Pages {i+1}-{i+len(chunk)}]"
        retries = 3
        for attempt in range(retries):
            try:
                # 60s timeout is enough for 3 pages
                response = requests.post(f"{endpoint}?key={api_key}", json=payload, timeout=60)
                
                if response.status_code == 200:
                    data = response.json()
                    candidates = data.get("candidates", [])
                    if candidates and "content" in candidates[0]:
                        c_parts = candidates[0]["content"].get("parts", [])
                        if c_parts and "text" in c_parts[0]:
                            chunk_text = c_parts[0]["text"].strip()
                            break # Success
                elif response.status_code == 429:
                    logging.warning(f"  Chunk {chunk_index} Rate Limit (429). Retrying...")
                    time.sleep(4 * (attempt + 1)) # Backoff
                elif response.status_code in [503, 500, 502, 504]:
                     wait_time = 2 * (attempt + 1)
                     logging.warning(f"  Chunk {chunk_index} Server Error ({response.status_code}). Retrying in {wait_time}s...")
                     time.sleep(wait_time)
                     continue
                else:
                    logging.error(f"  Chunk {chunk_index} Error {response.status_code}")
                    # Soft Fail: Don't crash, just break and keep the error message as text
                    break 

            except Exception as e:
                logging.error(f"  Chunk {chunk_index} Exception: {e}")
                time.sleep(2)
        
        all_extracted_text.append(chunk_text)
        
        # Small throttle between chunks
        if i + CHUNK_SIZE < len(pages_data):
            time.sleep(2)

    return "\n\n".join(all_extracted_text)

def evaluate_with_gemini(kb_text, student_answer):
    """
    Evaluates the student answer against the knowledge base.
    """
    api_key = current_app.config.get('GEMINI_API_KEY')
    endpoint = current_app.config.get('GEMINI_ENDPOINT')

    # Truncate KB if too long (though Flash handle 1M tokens, safe to limit somewhat for speed/cost if needed, but 8k is fine)
    truncated_kb = kb_text[:20000] 

    prompt = f"""
    You are a professional examiner evaluating handwritten student answers.    

    Knowledge Base:
    \"\"\"{truncated_kb}\"\"\"

    Student Answer:
    \"\"\"{student_answer}\"\"\"

    Please evaluate and return the result in the following clear format:

    Analyze thoroughly and provide:
    - **Total Marks** (out of 50)
    - **Relevance**
    - **Accuracy**
    - **Missing Key Points**
    - **Suggestions**
    - **One-line summary feedback**
    
    Format the output with Markdown for bolding headings (e.g. **Total Marks: 35/50**).
    """

    # Minimal pause to ensure sequential order
    time.sleep(2)

    payload = {
        "contents": [{
            "parts": [{"text": prompt}]
        }],
        "generationConfig": {
            "temperature": 0.0,
            "topK": 1
        }
    }

    retries = 10  # Increased from 5
    for attempt in range(retries):
        try:
            response = requests.post(f"{endpoint}?key={api_key}", json=payload, timeout=60)
            response.raise_for_status()
            data = response.json()

            candidates = data.get("candidates", [])
            if candidates and "content" in candidates[0]:
                parts = candidates[0]["content"].get("parts", [])
                if parts and "text" in parts[0]:
                    return parts[0]["text"]
            return "Evaluation failed (No content)."
            
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 429:
                # Aggressive backoff for free tier
                wait_time = 10 * (attempt + 1)
                
                logging.warning(f"Evaluation Rate limit hit (429). Retrying in {wait_time}s...")
                time.sleep(wait_time)
                continue
            
            if e.response.status_code in [500, 502, 503, 504]:
                wait_time = 2 * (attempt + 1)
                logging.warning(f"Gemini Server Error ({e.response.status_code}). Retrying in {wait_time}s...")
                time.sleep(wait_time)
                continue
            logging.exception(f"Gemini Evaluation Failed (HTTP {e.response.status_code}): {e}")
            return f"Error during evaluation: {e}"

        except Exception as e:
            logging.exception(f"Gemini Evaluation Failed: {e}")
            return f"Error during evaluation: {str(e)}"
            
    return "Error: Evaluation rate limit exceeded after retries. Please wait 1 minute and try again."
