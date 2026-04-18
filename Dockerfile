FROM python:3.11-slim

# Install system dependencies
# - build-essential, g++, python3-dev: for compiling C++ extensions (needed by some FlagEmbedding deps)
# - libmagic1: for file type detection
# - tesseract-ocr: for OCR
# - libpango-1.0-0, libharfbuzz0b, libpangoft2-1.0-0: for WeasyPrint (PDF generation)
RUN apt-get update && apt-get install -y \
    build-essential \
    g++ \
    python3-dev \
    libmagic1 \
    tesseract-ocr \
    libpango-1.0-0 \
    libharfbuzz0b \
    libpangoft2-1.0-0 \
    libgl1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Upgrade pip and install wheel
RUN pip install --no-cache-dir --upgrade pip wheel setuptools

# Copy consolidated requirements
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Force install FlagEmbedding specifically to ensure it's present
RUN pip install --no-cache-dir FlagEmbedding==1.3.2

# Verification step: if this fails, the build fails
RUN python3 -c "from FlagEmbedding import BGEM3FlagModel; print('SUCCESS: FlagEmbedding is installed and importable')"

# Copy the entire Neethi project
COPY . .

# Set Python path to include the root for backend imports
ENV PYTHONPATH=/app

# Hugging Face Spaces expects the application on port 7860
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "7860", "--loop", "asyncio"]
