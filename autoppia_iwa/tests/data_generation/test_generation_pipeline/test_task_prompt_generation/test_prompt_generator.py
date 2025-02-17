import unittest

from autoppia_iwa.src.bootstrap import AppBootstrap
from autoppia_iwa.src.data_generation.application.task_prompt_generator import TaskPromptGenerator
from autoppia_iwa.src.data_generation.domain.classes import TaskDifficultyLevel, TaskPromptForUrl
from autoppia_iwa.src.web_analysis.domain.analysis_classes import DomainAnalysis, LLMWebAnalysis


class TestTaskPromptGenerator(unittest.TestCase):
    """Unit tests for TaskPromptGenerator."""

    def setUp(self):
        """Set up test dependencies."""
        self.app_boostrap = AppBootstrap()
        self.llm_service = self.app_boostrap.container.llm_service()
        self.domain = "localhost:8000"
        self.test_data = self._get_mock_web_analysis()
        self.web_analysis = DomainAnalysis(**self.test_data)

    def _get_mock_web_analysis(self):
        test_data = {
            "domain": "localhost:8000",
            "status": "done",
            "analyzed_urls": [
                {
                    "page_url": "http://localhost:8000/",
                    "elements_analysis_result": [
                        {
                            "tag": "header",
                            "size": 3505,
                            "analysis": {
                                "one_phrase_summary": "A navigation header for a website.",
                                "summary": "This header contains a navigation menu with links to various sections of the website, including Home, About Us, Contact, and options for registration and login.",
                                "categories": [
                                    "Website Navigation",
                                    "User Interface",
                                    "Web Design",
                                ],
                                "functionality": "Users can click on the links to navigate to different pages, toggle the menu on smaller screens, and access registration or login options.",
                                "media_files_description": {"logo": "A website logo displayed as an image, providing brand identity."},
                                "key_words": [
                                    "navigation",
                                    "menu",
                                    "home",
                                    "about us",
                                    "contact",
                                    "register",
                                    "login",
                                ],
                                "relevant_fields": {
                                    "links": [
                                        {"href": "/", "target": ""},
                                        {"href": "#", "target": ""},
                                        {"href": "/employee/register", "target": ""},
                                        {"href": "/employer/register", "target": ""},
                                        {"href": "/login", "target": ""},
                                    ],
                                    "images": [{"src": "/static/img/itsourcecodes.jpg", "alt": "logo"}],
                                    "button": [
                                        {
                                            "type": "button",
                                            "aria-controls": "navbarSupportedContent",
                                            "aria-expanded": "false",
                                            "aria-label": "Toggle navigation",
                                        }
                                    ],
                                },
                                "curiosities": "",
                                "accessibility": "The navigation button includes aria attributes to enhance the browsing experience for assistive technologies.",
                            },
                            "children": [],
                        },
                        {
                            "tag": "div",
                            "size": 8165,
                            "analysis": {
                                "one_phrase_summary": "Login and job search section.",
                                "summary": "This section allows users to log in to their account or register for a new one, while also providing job search functionalities.",
                                "categories": [
                                    "User Authentication",
                                    "Job Search",
                                    "Career Development",
                                ],
                                "functionality": "Users can log in using email and password, register for a new account, and search for jobs based on position and location. Typical behaviors include filling out login credentials, clicking on 'Log in', and navigating to job offers.",
                                "media_files_description": "",
                                "key_words": [
                                    "customer login",
                                    "job search",
                                    "register",
                                    "login form",
                                    "job offers",
                                ],
                                "relevant_fields": {
                                    "form_fields": [
                                        {
                                            "type": "text",
                                            "id": "email_modal",
                                            "placeholder": "email",
                                        },
                                        {
                                            "type": "password",
                                            "id": "password_modal",
                                            "placeholder": "password",
                                        },
                                        {
                                            "type": "text",
                                            "id": "profession",
                                            "placeholder": "Position you are looking for",
                                        },
                                        {
                                            "type": "text",
                                            "id": "location",
                                            "placeholder": "Any particular location?",
                                        },
                                    ],
                                    "links": [
                                        {"href": "client-register.html"},
                                        {"href": "/jobs"},
                                    ],
                                },
                                "curiosities": "",
                                "accessibility": "The login modal has ARIA attributes for improved accessibility, including 'aria-labelledby' and 'aria-hidden' to assist screen readers.",
                            },
                            "children": [],
                        },
                        {
                            "tag": "footer",
                            "size": 2301,
                            "analysis": {
                                "one_phrase_summary": "Footer section providing information about jobs and the portal.",
                                "summary": "This footer section outlines the concept of jobs and employment while promoting the Online Itsourcecode Portal Jobs System 2021.",
                                "categories": [
                                    "Jobs",
                                    "Employment",
                                    "Career Development",
                                    "Online Portals",
                                ],
                                "functionality": "This section serves to inform users about job-related concepts and serves as a promotional area for the job portal. Users might interact by reading the content or seeking further information on job opportunities.",
                                "media_files_description": "",
                                "key_words": [
                                    "jobs",
                                    "employment",
                                    "occupation",
                                    "career",
                                    "Online Itsourcecode Portal",
                                    "2021",
                                ],
                                "relevant_fields": "",
                                "curiosities": "The repeated emphasis on the definition of jobs suggests a focus on educating users about employment.",
                                "accessibility": "The text content is straightforward, aiming for clarity and understanding, which is beneficial for accessibility.",
                            },
                            "children": [],
                        },
                    ],
                    "web_summary": {
                        "one_phrase_summary": "A comprehensive web portal for job search and user authentication.",
                        "summary": "The website serves as a platform for users to log in, register for accounts, search for jobs, and access essential navigation links.",
                        "categories": [
                            "Website Navigation",
                            "User Authentication",
                            "Job Search",
                            "Career Development",
                        ],
                        "functionality": [
                            "Users can navigate through the header to different sections, log in with email and password, register for new accounts, and search for job offers by entering profession and location.",
                            "Typical interactions include clicking navigation links, submitting login forms, and exploring job listings.",
                        ],
                        "media_files_description": [{"logo": "A website logo displayed as an image, providing brand identity."}],
                        "key_words": [
                            "navigation",
                            "menu",
                            "home",
                            "about us",
                            "contact",
                            "register",
                            "login",
                            "customer login",
                            "job search",
                            "job offers",
                        ],
                        "curiosities": "The footer emphasizes job definitions, indicating an educational focus on employment concepts.",
                        "accessibility": "The site incorporates ARIA attributes for improved accessibility in navigation and login features.",
                        "user_experience": "Users can easily navigate through the header to find sections like Home and Contact, use forms to log in or register, and search for job listings based on their preferences.",
                        "advertisements": "",
                        "seo_considerations": "",
                        "additional_notes": "The structure supports intuitive navigation and user-friendly interactions for job seekers.",
                    },
                    "html_source": '<html>\n <head>\n  <meta charset="utf-8"/>\n  <meta content="IE=edge" http-equiv="X-UA-Compatible"/>\n  <title>\n   Home\n - Online Job Portal System\n  </title>\n  <meta content=""/>\n  <meta content="width=device-width, initial-scale=1"/>\n  <meta content="all,follow"/>\n  <!-- Bootstrap CSS-->\n  <link href="/static/vendor/bootstrap/css/bootstrap.min.css" rel="stylesheet"/>\n  <!-- Font Awesome CSS-->\n  <link href="/static/vendor/font-awesome/css/font-awesome.min.css" rel="stylesheet"/>\n  <!-- Google fonts - Roboto for copy, Montserrat for headings-->\n  <link href="http://fonts.googleapis.com/css?family=Roboto:300,400,700" rel="stylesheet"/>\n  <link href="http://fonts.googleapis.com/css?family=Montserrat:400,700" rel="stylesheet"/>\n  <!-- owl carousel-->\n  <link href="/static/vendor/owl.carousel/assets/owl.carousel.css" rel="stylesheet"/>\n  <link href="/static/vendor/owl.carousel/assets/owl.theme.default.css" rel="stylesheet"/>\n  <!-- theme stylesheet-->\n  <link href="/static/css/style.default.css" id="theme-stylesheet" rel="stylesheet"/>\n  <link id="new-stylesheet" rel="stylesheet"/>\n  <!-- Custom stylesheet - for your changes-->\n  <link href="/static/css/custom.css" rel="stylesheet"/>\n  <!-- Favicon-->\n  <link href="favicon.png" rel="shortcut icon"/>\n  <!-- Tweaks for older IEs-->\n  <!--[if lt IE 9]>\n    <script src="https://oss.maxcdn.com/html5shiv/3.7.3/html5shiv.min.js"></script>\n    <script src="https://oss.maxcdn.com/respond/1.4.2/respond.min.js"></script><![endif]-->\n </head>\n <body>\n  <!-- navbar-->\n  <header>\n   <nav>\n    <div>\n     <a href="/">\n      <img alt="logo" src="/static/img/itsourcecodes.jpg"/>\n      <span>\n       Home\n      </span>\n     </a>\n     <button aria-controls="navbarSupportedContent" aria-expanded="false" aria-label="Toggle navigation" type="button">\n      Menu\n      <i>\n      </i>\n     </button>\n     <div id="navbarSupportedContent">\n      <ul>\n       <li>\n        <a href="/">\n         Home\n         <span>\n          (current)\n         </span>\n        </a>\n       </li>\n       <li>\n        <a href="#">\n         About Us\n        </a>\n       </li>\n       <li>\n        <a href="#">\n         Contact\n        </a>\n       </li>\n       <li>\n        <a aria-expanded="false" aria-haspopup="true" href="#" id="pages">\n         <i>\n         </i>\n         Register\n        </a>\n        <div aria-labelledby="pages">\n         <a href="/employee/register">\n          Employee\n         </a>\n         <a href="/employer/register">\n          Employers\n         </a>\n        </div>\n       </li>\n       <li>\n        <a href="/login">\n         <i>\n         </i>\n         Login\n        </a>\n       </li>\n      </ul>\n     </div>\n    </div>\n   </nav>\n  </header>\n  <div>\n   <div aria-hidden="true" aria-labelledby="exampleModalLabel" id="loginModal" role="dialog" tabindex="-1">\n    <div role="document">\n     <div>\n      <div>\n       <h4 id="exampleModalLabel">\n        Customer Login\n       </h4>\n       <button aria-label="Close" type="button">\n        <span aria-hidden="true">\n         ×\n        </span>\n       </button>\n      </div>\n      <div>\n       <form action="" method="post">\n        <div>\n         <input id="email_modal" placeholder="email" type="text"/>\n        </div>\n        <div>\n         <input id="password_modal" placeholder="password" type="password"/>\n        </div>\n        <p>\n         <button type="button">\n          <i>\n          </i>\n          Log in\n         </button>\n        </p>\n       </form>\n       <p>\n        Not registered yet?\n       </p>\n       <p>\n        <a href="client-register.html">\n         <strong>\n          Register now\n         </strong>\n        </a>\n        ! It is easy and done in 1 minute and gives you access to special\n                        discounts and much more!\n       </p>\n      </div>\n     </div>\n    </div>\n   </div>\n   <!-- *** LOGIN MODAL END ***-->\n   <section>\n    <div>\n     <div>\n      <div>\n       <div>\n        <h2>\n         Find a job that will fit to your expertise.\n        </h2>\n        <form action="/search" id="job-main-form" method="get">\n         <div>\n          <div>\n           <div>\n            <div>\n             <label for="profession">\n              Position\n             </label>\n             <input id="profession" placeholder="Position you are looking for" type="text"/>\n            </div>\n           </div>\n           <div>\n            <div>\n             <label for="location">\n              Location\n             </label>\n             <input id="location" placeholder="Any particular location?" type="text"/>\n            </div>\n           </div>\n           <div>\n            <button type="submit">\n             <i>\n             </i>\n            </button>\n           </div>\n          </div>\n         </div>\n        </form>\n       </div>\n      </div>\n     </div>\n    </div>\n   </section>\n   <section>\n    <div>\n     <h3>\n      Featured jobs\n     </h3>\n     <div>\n     </div>\n    </div>\n   </section>\n   <section>\n    <div>\n     <h4>\n      Trending this month\n     </h4>\n    </div>\n   </section>\n   <section>\n    <div>\n    </div>\n    <div>\n     <div>\n      <div>\n       <p>\n        Start searching for your new job now!\n       </p>\n       <p>\n        <a href="/jobs">\n         See our job offers\n        </a>\n       </p>\n      </div>\n     </div>\n    </div>\n   </section>\n  </div>\n  <footer>\n   <div>\n    <div>\n     <div>\n      <div>\n       <h4>\n        About Jobs\n       </h4>\n       <p>\n        A job, employment, work or occupation, is a person\'s role in society. More specifically, a job\n                        is an activity, often regular and often performed in exchange for payment. Many people have\n                        multiple jobs. A person can begin a job by becoming an employee, volunteering, starting a\n                        business, or becoming a parent.\n       </p>\n      </div>\n     </div>\n    </div>\n   </div>\n   <div>\n    <div>\n     <div>\n      <div>\n       <p>\n        Online Itsourcecode Portal Jobs System 2021\n       </p>\n      </div>\n     </div>\n    </div>\n   </div>\n  </footer>\n </body>\n</html>\n',
                }
            ],
            "started_time": "2024-12-20 21:37:17",
            "ended_time": "2024-12-20 21:37:56",
            "total_time": 38.87642955780029,
            "start_url": "http://localhost:8000/",
        }
        test_data["analyzed_urls"][0]["web_summary"] = LLMWebAnalysis(**test_data["analyzed_urls"][0]["web_summary"])
        return test_data

    def test_generate_prompts(self):
        """Test the generation of prompts for a domain."""
        generator = TaskPromptGenerator(web_analysis=self.web_analysis, llm_service=self.llm_service)
        tasks = generator.generate_prompts_for_domain(task_difficulty_level=TaskDifficultyLevel.MEDIUM)

        # Assertions
        self.assertIsNotNone(tasks, "Tasks should not be None.")
        self.assertIsInstance(tasks, list, "Tasks should be a list.")
        self.assertTrue(all(isinstance(task, TaskPromptForUrl) for task in tasks), "All tasks should be instances of TaskPromptForUrl.")

        print(f"Generated Tasks: {tasks}")


if __name__ == "__main__":
    unittest.main()
