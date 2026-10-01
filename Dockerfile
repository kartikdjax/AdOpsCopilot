FROM python:3.10-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    HF_HOME=/opt/hf \
    ANONYMIZED_TELEMETRY=False

# CPU-only torch first: sentence-transformers would otherwise pull the CUDA
# build, several GB the embeddings don't need.
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu --extra-index-url https://pypi.org/simple
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Bake the embedding model into the image, then run offline: no Hugging Face
# calls at startup, and no dependency on huggingface.co being reachable.
ARG EMBEDDING_MODEL=all-MiniLM-L6-v2
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('${EMBEDDING_MODEL}')"
ENV HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1

COPY src ./src
COPY static ./static

# Named entry points, so `netstat -p` / `ps` on the server show what is
# listening (AdOps-Copilot) rather than a bare "python3.10". Python started
# through these names behaves exactly as python3.10, and its worker
# processes inherit the name.
RUN ln -s /usr/local/bin/python3.10 /usr/local/bin/AdOps-Copilot \
 && ln -s /usr/local/bin/python3.10 /usr/local/bin/AdOps-Scheduler

# data/ holds the user database and the Chroma knowledge base; mount a volume there.
VOLUME ["/app/data"]
EXPOSE 8000
CMD ["AdOps-Copilot", "-m", "uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
