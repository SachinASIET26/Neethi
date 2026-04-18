FROM python:3.11-slim

# Install system dependencies
# - libmagic1: for file type detection
# - tesseract-ocr: for OCR
# - libpango-1.0-0, libharfbuzz0b, libpangoft2-1.0-0: for WeasyPrint (PDF generation)
# - libpq-dev: for PostgreSQL (if building from source)
RUN apt-get update && apt-get install -y \
    build-essential \
    libmagic1 \
    tesseract-ocr \
    libpango-1.0-0 \
    libharfbuzz0b \
    libpangoft2-1.0-0 \
    libgl1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy consolidated requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the entire Neethi project
COPY . .

# Set Python path to include the root for backend imports
ENV PYTHONPATH=/app

# Hugging Face Spaces expects the application on port 7860
# Using --loop asyncio for CrewAI compatibility
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "7860", "--loop", "asyncio"]
