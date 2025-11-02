FROM python:3.10-slim

WORKDIR /scr

RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN curl -LsSf https://github.com/astral-sh/uv/releases/download/0.2.12/uv-installer.sh | sh

COPY requirements.txt .

RUN /root/.cargo/bin/uv pip install --system --no-cache -r requirements.txt

COPY . .

EXPOSE 8003

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8003"]