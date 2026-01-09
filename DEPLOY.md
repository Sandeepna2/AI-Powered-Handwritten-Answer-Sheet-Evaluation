# Deployment Instructions

Your application is ready for deployment on **Render** (recommended) or Heroku.

## Deploy to Render (Easiest)

1.  **Push your code to GitHub**.
2.  Go to [dashboard.render.com](https://dashboard.render.com/).
3.  Click **New +** -> **Web Service**.
4.  Connect your GitHub repository.
5.  **Build Command**: `pip install -r requirements.txt`
6.  **Start Command**: `gunicorn run:app`
7.  **Environment Variables**:
    *   Add `GEMINI_API_KEY`: (Your Google Gemini API Key)
    *   Add `SECRET_KEY`: (A random string)

The `Procfile` and `runtime.txt` are already included to help Render detect the configuration automatically.
