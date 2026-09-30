# Production image for the FastAPI backend (Render).
#
# ffmpeg is required at runtime by agents/video_summary_agent.py
# (yt-dlp audio extraction + pydub chunking) -- Render's native Python
# runtime doesn't include it, hence a Docker-based service instead.
#
# Local dev is unaffected by this file: keep using
#   uvicorn main:app --host 127.0.0.1 --port 8000 --reload
# directly on your machine/venv, same as always.

FROM python:3.13-slim

# ffmpeg: required by yt-dlp/pydub for YouTube + uploaded-video audio.
# libgl1/libglib2.0-0: common runtime libs Pillow/sentence-transformers'
# transitive deps (e.g. opencv-headless-style wheels) expect on slim
# images; harmless if unused.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Installed as its own layer so dependency installs are cached across
# builds where only application code changed.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Render sets $PORT at runtime; 10000 is only the documented Render
# default used if $PORT is somehow unset (e.g. running this image
# outside Render).
ENV PORT=10000
EXPOSE 10000

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT}"]
