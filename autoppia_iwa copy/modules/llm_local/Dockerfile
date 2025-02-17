# Step 1: Use Python 3.10 as the base image
FROM python:3.10-slim-bullseye

# Step 2: Install necessary system dependencies
RUN apt-get update -y && \
    apt-get upgrade -y && \
    apt-get install -y \
    sudo \
    python3-pip \
    python3-dev \
    python3-venv \
    build-essential \
    cmake \
    wget \
    npm && \
    rm -rf /var/lib/apt/lists/*

# (QUITAR) # ENV CUDA_VERSION=cu121
# (QUITAR o cambiar a off) # ENV CMAKE_ARGS="-DGGML_CUDA=on"
# (QUITAR) # ENV FORCE_CMAKE=1

# Step 3: Actualiza pip antes de instalar cualquier paquete
RUN pip install --upgrade pip

# Step 4: Instala llama-cpp-python (CPU-Only)
# Ya no uses la URL extra de CUDA. Instala directamente desde PyPI (CPU):
RUN pip install --no-cache-dir llama-cpp-python==0.2.90

# Step 5: Install Python project dependencies
COPY local_llm_requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Step 6: Download the model file from Hugging Face
WORKDIR /app
RUN wget https://huggingface.co/Qwen/Qwen2.5-Coder-14B-Instruct-GGUF/resolve/main/qwen2.5-coder-14b-instruct-q4_k_m.gguf

# Step 7: Install PM2 for process management
RUN npm install pm2 -g

# Step 8: Copy application files
COPY run_local_llm.py /app/run_local_llm.py

# Step 9: Expose port 6000
EXPOSE 6000

# Step 10: Define the entrypoint
ENTRYPOINT ["pm2-runtime", "start", "run_local_llm.py", "--name", "llm_local", "--interpreter", "python3.10"]