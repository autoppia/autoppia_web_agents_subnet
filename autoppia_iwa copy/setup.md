# Project Setup Guide

This guide will walk you through setting up and running the project locally on a Linux machine. It includes steps to
install Python 3.10 or above, set up a virtual environment or Conda environment, install Playwright, and configure the
project dependencies.

## **1. Introduction**

To ensure the proper functioning of the project, three essential components need to be running simultaneously:

1. **run_local_llm.py**: Local model server (used if you don't want to use the Runpod serverless model). Check the
   [Model Deployment Guide](llm_local/llm_local_setup.md): Step-by-step instructions for deploying the local model.

2. **webApp/app.py** OR **app.py**: Main project's endpoints that handle the core functionality of the project.

    - **webApp/app.py** _**(Not used now)**_: This file is used for managing socketio for _WebApp_.

    - **app.py**: Serves as the main flask entry point for the application. It initializes the application and handles
      API requests related to running benchmarks [Project Guide For Local Testing](setup.md) -> current file

3. **Demo (Django) app**: Runs the demo application for testing purposes (check its own **setup.md**)

> **Important:** Check the following steps and ports to starting all projects

### **1.1 Ports and Configurations**

The table below outlines the ports used by different applications in the project for easier configuration and reference.

| **Port** | **Application**                | **Description**                                                 |
|----------|--------------------------------|-----------------------------------------------------------------|
| `5000`   | Benchmark Flask App (`app.py`) | Default port for running the Flask development server.          |
| `8080`   | WebApp (`webApp/app.py`)       | Common port for running frontend (flask socketio) applications. |
| `8000`   | Django App (`manage.py`)       | Default port for running the Django development server.         |
| `6000`   | Local LLM Model Server         | Custom port for hosting the local LLM inference model.          |
| `27017`  | MongoDB                        | Default port for MongoDB database server.                       |
| `5432`   | PostgreSQL                     | Default port for PostgreSQL database server.                    |
| `3306`   | MySQL                          | Default port for MySQL database server.                         |

> **Note**: Update your configuration files and environment variables if custom ports are required. Ensure that these
> ports are open and accessible within your network.

### **1.2 Model Information and GPU Requirements**

| Model Name             | Variant | Model Link                                                                             | GPU Memory Requirement | Open Source |
|------------------------|---------|----------------------------------------------------------------------------------------|------------------------|-------------|
| **Qwen 2.5 Coder 32B** | Q2_K    | [Qwen2.5-Coder-32B Model](https://huggingface.co/Qwen/Qwen2.5-Coder-32B-Instruct-GGUF) | 18 GB                  | Yes         |
| **Qwen 2.5 Coder 14B** | Q4_K_M  | [Qwen2.5-Coder-14B Model](https://huggingface.co/Qwen/Qwen2.5-Coder-14B-Instruct-GGUF) | 18 GB                  | Yes         |
| **Hermes LLAMA 3.1**   | Q4_K_M  | [LLAMA Model](https://huggingface.co/NousResearch/Hermes-3-Llama-3.1-8B-GGUF)          | 12 GB                  | Yes         |

This table provides the **model name**, a **link** to the model, and the **GPU memory requirements** for each model. Be
sure to have the appropriate hardware or cloud setup to meet these requirements when using the
models for inference or training.
Here’s an updated section for the setup guide with the new point added:

---

## **2. Project Setup**

### **Prerequisites**

- **Python 3.10 or above**: Ensure Python 3.10+ is installed on your system.
- **pip**: Python's package manager.
- **Conda (Optional)**: If you prefer Conda for managing environments.
- **sudo/root privileges**: Required for installing system dependencies.
- **MongoDB**: Ensure MongoDB is running locally or on a cloud cluster. You can update the MongoDB connection in the
  `.env` file by modifying the following line:

```dotenv
   MONGODB_URL="YOUR_MONGODB_URL"
```

- **Django App Database**: A database is required for the Django application. Follow the database setup instructions
  provided in the guide above to configure and connect your preferred database (check its own setup.md)

---

## INSTALLATION

## **Step 1: Verify Python Installation**

Check your Python version:

```bash
python3 --version
```

If the version is earlier than 3.10, you'll need to install the correct version. On Ubuntu, you can use:

```bash
sudo apt update
sudo apt install -y python3.10 python3.10-venv python3-pip
```

---

## **Step 2: Choose Environment Setup**

### Option 1: Set Up a Virtual Environment with `venv`

1. Create a virtual environment:

   ```bash
   python3 -m venv venv
   ```

   > **Note**:If you encounter issues with Python versions, ensure you are using Python 3.10 or higher. You can specify
   > the version when running commands:

   ```bash
   python3.10 -m venv venv
   ```

2. Activate the virtual environment:
   ```bash
   source venv/bin/activate
   ```

---

### Option 2: Set Up a Conda Environment

1. Ensure Conda is installed. Check with:

   ```bash
   conda --version
   ```

   If Conda is not installed on your system, you can download and install it
   from [Anaconda](https://www.anaconda.com/products/distribution) for a full-featured package
   or [Miniconda](https://docs.conda.io/en/latest/miniconda.html) for a lightweight version.

2. Create a new Conda environment:

   ```bash
   conda create -n autoppia python=3.10 -y
   ```

3. Activate the environment:
   ```bash
   conda activate autoppia
   ```

---

## **Step 3: Install Dependencies**

1. Install Python dependencies:

   ```bash
   pip install -r requirements.txt
   ```

2. Install Playwright and its browser binaries:

   ```bash
   python3 -m playwright install
   ```

   This will download the necessary browser binaries for Playwright (Chromium, Firefox, and WebKit).

---

## **Step 4: Set Up the Environment File (Only if You Don't Have One Already)**

1. **Create the `.env` File**:  
   If you don't have a `.env` file in your project directory, create one by running:

   ```bash
   touch .env
   ```

2. **Add the Required Environment Variables**:  
   Copy and paste the following into your `.env` file only if the .env is not existing, customizing values where
   necessary.

   ```env
    # Can be "serverless", "local" and "openai"
    LLM_PROVIDER="local"
    
    # Local LLM Configuration
    #LLM_ENPOINT="http://192.168.0.103:6000/generate"
    LLM_ENPOINT="http://69.55.141.126:10278/generate"
    
    # OpenAI Configuration
    OPENAI_API_KEY=""
    OPENAI_MODEL="gpt-4-32k-0613"
    OPENAI_MAX_TOKENS="2000"
    OPENAI_TEMPERATURE="0.7"
    
    # MongoDB Configuration
    MONGODB_URL="mongodb://localhost:27017"
   ```

3. **Verify Environment Variables**:  
   To ensure all environment variables are correctly set, use:
   ```bash
   cat .env
   ```
   Confirm that all necessary keys and paths are present.

---

## **Step 5: Test Browser User Profile Through Login**

This script tests browser automation with a persistent user profile. Here's what it does:

1. **Setup and Launch**: Loads the user profile directory from environment variables and launches a Chromium browser
   with the saved session data if any, otherwise it will created new profile.

2. **Authentication Check**:

    - If the user is logged in, it skips to event handling.
    - If not, it registers a new user or logs in if registration fails.

3. **Event Processing**: Retrieves events, saves them to the database, and optionally deletes them.

4. **Clean Up**: Closes the browser gracefully after all operations.

### **How to Run**:

1. Set up `.env` with `PROFILE_DIR` or use the default profile directory.
2. Run the script using:
   ```bash
   python3 tests/test_playwright_browser/ensure_chrome_profile.py
   ```

---

## **Step 6: Run Applications**

### Flask API Application

Run the Flask application:

   ```bash
   python3 app.py
   ```

By default, Flask will run the application at `http://127.0.0.1:5000/`.  
You can interact with it using a browser, **Postman**, or **cURL**.

---

## **Step 7: Running All Tests**

This section outlines how to execute tests for various components, including task generation, action generation, and
task execution with evaluation.

---

### **Task Generation Tests**

To test task generation logic, run:

```bash
python3 tests/test_tasks_generator/test_generate_task_prompts.py
```

---

### **Action Generation Tests**

To test action generation functionality, execute:

```bash
python3 tests/test_actions/test_actions_generation.py
```

---

### **Task Execution and Evaluation Tests**

#### **1. Single Task Execution**

To test the execution and evaluation of a single task, use:

```bash
python3 tests/task_execution_and_evaluation/test_execute_one_task.py
```

#### **2. Complete Task Generation and Execution**

> **Note**: This process may take some time and might not execute all tasks completely due to system or resource
> limitations.

To test the entire process of task generation followed by execution and evaluation, run:

```bash
python3 tests/test_tasks_generator/test_generate_tasks.py
```

---

### **Notes**

1. **Environment Activation**:

    - For `venv`: Activate the environment each time with `source venv/bin/activate`.
    - For Conda: Activate the environment with `conda activate autoppia`.

2. **Playwright Browsers**:
   Ensure the browsers are installed correctly by running:

   ```bash
   python3 -m playwright install
   ```

   OR

   ```bash
   playwright install
   ```

3. **Dependencies**:
   If you add or update dependencies, make sure to update `requirements.txt`:

   ```bash
   pip freeze > requirements.txt
   ```

Now your project should be ready to run! If you encounter issues, double-check the steps or refer to the project
documentation.
