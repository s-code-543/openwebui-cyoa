FROM python:3.12-slim

WORKDIR /app

# Install system dependencies (gcc for Python packages, ffmpeg for audio conversion)
RUN apt-get update && apt-get install -y \
    gcc \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project files
COPY . .

# Expose debugpy port and Django port
EXPOSE 5678 8000

# Force unbuffered Python output so logs appear immediately
ENV PYTHONUNBUFFERED=1

# Run with debugpy for remote debugging (attach at your convenience)
CMD ["python", "-Xfrozen_modules=off", "-m", "debugpy", "--listen", "0.0.0.0:5678", "manage.py", "runserver", "0.0.0.0:8000"]
