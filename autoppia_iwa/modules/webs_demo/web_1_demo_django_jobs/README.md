# **Purpose of This Web App**

This web application is one of several examples designed to test and evaluate our **web agents** in a controlled
environment. The app simulates a realistic use case (an online job portal) to generate, emit, and store events that can
be used to assess the performance and functionality of web agents.

### **Key Objectives**:

1. **Part of a Broader Testing Ecosystem**:  
   As one of many web applications in our evaluation suite, this app contributes to creating diverse scenarios for
   testing web agents' ability to handle real-world tasks.

2. **Event Emission and Logging**:  
   The app generates events such as:

    - User registrations.
    - Job postings.
    - Resume uploads.
    - Application submissions.  
      These events can be:
    - **Emitted** for agents to observe and act upon in real time.
    - **Logged** and stored in the database for agents to query and process historical data.

3. **Database Integration**:  
   All interactions are stored systematically in the database. This enables agents to retrieve, interpret, and analyze
   structured data during their evaluations.

4. **Evaluation of Tasks**:  
   By providing realistic workflows (e.g., posting jobs, managing applications), the app allows us to evaluate agents’
   ability to complete specific tasks, process complex interactions, and generate meaningful outputs.

5. **Scalable Testing Environment**:  
   This app, alongside others, creates a modular and flexible testing ecosystem where agents can be benchmarked across
   various scenarios, ensuring scalability and repeatability of evaluations.

In summary, this web app serves as a versatile platform to test web agents' responsiveness to events, ability to process
data, and overall performance within a realistic job portal scenario.

# **What is this project about?**

An Online Job Portal Project in Django is a platform for job seekers to find appropriate jobs while companies can
publish their vacancies and find good candidates.

Jobseekers can:

1. Post their resumes.
2. Browse for job searches.
3. View personal work listings.

Companies can:

1. Post job details and vacancies.
2. Scan applicant resumes.

Example Workflow to Create a User:

1. Navigate to the registration endpoint: POST /users/
2. Provide the necessary information (username, email, password, etc.).
3. Submit the form to create a new user account.

# **Django Application Setup Guide**

This guide provides step-by-step instructions to set up and run a Django application in your development environment.
Follow these steps carefully to ensure the application is configured correctly.

> **Note**: For an automated setup, you can use the setup script provided in the repository. Simply run
> the [setup script](README.md), which will:
>
> - Create a virtual environment (`venv_django`)
> - Install the required dependencies
> - Perform database migrations
> - Start the server in the background using a `pm2` (as `django-server`).

---

## **1. Prerequisites**

Before setting up the Django app, make sure the following are installed:

0. **Clone the Repository**  
   Begin by cloning the repository to your local machine:

   ```bash
   git clone https://github.com/autoppia/online_job_portal.git
   ```

   Then, navigate to the project directory:

   ```bash
   cd online_job_portal
   ```

1. **Python 3.10 or Above**  
   The project requires Python 3.10 or above. To check your Python version, run:
   ```bash
   python3 --version
   ```
2. **pip**  
   Python's package manager, typically included with Python installations. Verify:
   ```bash
   pip --version
   ```
3. **Virtual Environment Tool**  
   (e.g., `venv`). It’s included with Python 3. Ensure you can create virtual environments:

   ```bash
   python3.10 -m venv --help
   ```

4. **Database**  
   Depending on the project, you may need a database such as:
    - **SQLite**: Default, lightweight option.
    - **PostgreSQL**: Common for production-grade applications.
    - **MySQL**: Alternative for relational databases.

---

## **2. Setting Up the Virtual Environment**

1. Create a virtual environment:

   ```bash
   python3.10 -m venv venv
   ```

2. Activate the virtual environment:

    - **Linux/macOS**:
      ```bash
      source venv/bin/activate
      ```
    - **Windows**:
      ```bash
      venv\Scripts\activate
      ```

3. Upgrade pip to the latest version:
   ```bash
   pip install --upgrade pip
   ```

---

## **3. Installing Dependencies**

Install all Python dependencies specified in the `requirements.txt` file:

```bash
pip install -r requirements.txt
```

---

## **4. Configuring the Database**

### **Default (SQLite)**

If using SQLite (default), no additional setup is required.

### **PostgreSQL or MySQL**

1. Install the necessary Python database drivers:

    - PostgreSQL:
      ```bash
      pip install psycopg2-binary
      ```
    - MySQL:
      ```bash
      pip install mysqlclient
      ```

2. Update the database settings in the `settings.py` file:
   ```python
   DATABASES = {
       'default': {
           'ENGINE': 'django.db.backends.postgresql',  # Use 'django.db.backends.mysql' for MySQL
           'NAME': '<database_name>',
           'USER': '<database_user>',
           'PASSWORD': '<database_password>',
           'HOST': 'localhost',
           'PORT': '5432',  # Use '3306' for MySQL
       }
   }
   ```
   Replace placeholders (`<database_name>`, `<database_user>`, etc.) with your database credentials.

---

## **5. Migrating the Database**

Apply migrations to set up the database schema:

```bash
python3.10 manage.py makemigrations
```

```bash
python3.10 manage.py migrate
```

---

## **6. Creating a Superuser**

Create an admin user for accessing the Django Admin panel:

```bash
python3.10 manage.py createsuperuser
```

Follow the prompts to set the username, email, and password.

---

## **7. Running the Development Server in a `screen` Session**

To run the Django development server in the background using a `screen` session, follow these steps:

1. **Install `screen`** (if not already installed):
   ```bash
   sudo apt-get install screen
   ```

2. **Start a New Screen Session**:
   ```bash
   screen -S django-server
   ```
   This starts a new screen session named `django-server`.

3. **Activate the Virtual Environment** (if you have one):
   ```bash
   source venv/bin/activate
   ```

4. **Run the Development Server**:
   ```bash
    python manage.py seed_db && python3.10 manage.py runserver
   ```
   The server will start at `http://127.0.0.1:8000/`.

5. **Detach from the Screen Session**:
   Press `Ctrl + A`, then `D` to detach from the screen session, allowing the server to continue running in the
   background.

6. **Reattach to the Screen Session**:
   To view the server output or stop the server, reattach to the screen session:
   ```bash
   screen -r django-server
   ```
