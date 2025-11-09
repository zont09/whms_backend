# ======================
# FastAPI Chat Backend
# ======================
FROM python:3.10-slim

# Set working directory
WORKDIR /app

# Install system dependencies (needed for motor, bson, etc.)
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv (fast pip alternative)
RUN curl -LsSf https://github.com/astral-sh/uv/releases/download/0.2.12/uv-installer.sh | sh

# Copy dependencies file first for better caching
COPY requirements.txt .

# Install dependencies globally using uv
RUN /root/.cargo/bin/uv pip install --system --no-cache -r requirements.txt

# Copy project files
COPY . .

# Expose FastAPI port (chat backend)
EXPOSE 8001

# Default command
CMD ["uvicorn", "chat_server:app", "--host", "0.0.0.0", "--port", "8001", "--reload"]
