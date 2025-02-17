## **Setup Guide: Running a Local Model for Inference**

This guide explains how to set up and deploy a large language model (LLM) locally, ensuring proper configuration for
dependencies, GPU compatibility, and runtime environment.

---

### **Prerequisites**

- **POD TYPE** I suggest get A40 in Runpod
- **CUDA 12.1 or above**: Required for `llama-cpp-python` to work correctly with GPU acceleration.
- **MEMORY POD 200GB**: Required for the model.
- **Python 3.10 or above**: Verify your Python installation meets this requirement.
- **pip**: Python's package manager.

> **Important:** To use the local model, ensure the `LLM_ENPOINT` variable in the `.env` file is set to
> **'true'**

---

### **Environment Setup Options**

You can choose between using a virtual environment (`venv`) or a Conda environment. Both methods are detailed below.

---

#### **Option 1: Virtual Environment with `venv`**

1. Create a virtual environment:

   ```bash
   python3 -m venv venv
   ```

2. Activate the virtual environment:

   ```bash
   source venv/bin/activate
   ```

3. Once activated, follow the installation steps outlined below.

---

#### **Option 2: Conda Environment Setup**

1. [Install Miniconda](https://docs.conda.io/en/latest/miniconda.html) if it's not already installed.

2. Create a new Conda environment:

   ```bash
   conda create -n project_env python=3.10 -y
   ```

3. Activate the Conda environment:

   ```bash
   conda activate project_env
   ```

4. Once activated, follow the installation steps outlined below.

---

### **Installation Steps**

Follow these commands directly in your terminal after setting up your environment.

---
```bash
setup.sh
```

#### **Optional**

The downloaded model file is saved as `qwen2.5-coder-32b-instruct-q4_k_m.gguf`. If you need to use a different model or
path, update the model path in `test.py`.

---

## Start the LLM service using PM2
```bash
echo "Starting the LLM service in the background using PM2..."
pm2 start autoppia_iwa/modules/llm_local/run_local_llm.py --name llm_local --interpreter ./llm_env/bin/python -- --port 6000
echo "Setup complete. LLM service is running on port 6000 in the background."
```

In addition, a test has been created in the test folder you can run it using

```bash
python3 autoppia_iwa/modules/llm_local/test/test.py
```

If you encounter issues, verify the CUDA version, Python installation, and network connectivity to the local model
server.

