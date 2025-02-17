import unittest

from autoppia_iwa.src.bootstrap import AppBootstrap
from autoppia_iwa.src.web_analysis.application.web_analysis_pipeline import WebAnalysisPipeline


class TestWebAnalysisPipelineWithCache(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        """Set up resources for all tests."""
        cls.app_boostrap = AppBootstrap()
        cls.analysis_repository = cls.app_boostrap.container.analysis_repository()
        cls.llm_service = cls.app_boostrap.container.llm_service()
        cls.enable_crawl = False
        cls.data = {
            "domain": "localhost:8000",
            "status": "done",
            "analyzed_urls": [
                {
                    "page_url": "http://localhost:8000/employee/register",
                    "elements_analysis_result": [
                        {
                            "tag": "header",
                            "size": 3505,
                            "analysis": {
                                "one_phrase_summary": "The header contains navigation links and a logo for a website.",
                                "summary": "The header element includes a navigation menu with links to various pages such as Home, "
                                "About Us, Contact, Register, Employee, and Login. It also features a logo image that links back"
                                " to the homepage.",
                                "categories": [
                                    "Web Design",
                                    "User Interface",
                                    "Navigation",
                                    "Homepage",
                                ],
                                "functionality": [
                                    "Provides quick access to important pages and sections of the website",
                                    "Displays the website's logo and links back to the homepage",
                                    "Allows users to navigate to different parts of the site easily",
                                ],
                                "media_files_description": [
                                    {
                                        "tag": "img",
                                        "src": "/static/img/itsourcecodes.jpg",
                                        "alt": "logo",
                                    }
                                ],
                                "key_words": [
                                    "navigation",
                                    "menu",
                                    "logo",
                                    "homepage",
                                    "links",
                                    "website",
                                ],
                                "relevant_fields": [
                                    {"tag": "a", "href": "/"},
                                    {"tag": "a", "href": "#"},
                                    {"tag": "a", "href": "/employee/register"},
                                    {"tag": "a", "href": "/employer/register"},
                                    {"tag": "a", "href": "/login"},
                                ],
                                "curiosities": None,
                                "accessibility": [
                                    "The navigation menu is accessible using a keyboard",
                                    "The logo links back to the homepage for easy navigation",
                                    "The website structure is logical and easy to navigate",
                                ],
                            },
                            "children": [],
                        },
                        {
                            "tag": "div",
                            "size": 4606,
                            "analysis": {
                                "one_phrase_summary": "A registration form for creating a new account with options for first name, last name, " "email, password, confirm password, and gender.",
                                "summary": "This section contains a registration form that allows users to create a new account by providing "
                                "personal information such as their first name, last name, email address, password, confirm password, "
                                "and gender. The form also includes a password-based authentication option and a 'Register' button to "
                                "submit the information.",
                                "categories": [
                                    "Registration",
                                    "Account Creation",
                                    "User Authentication",
                                    "Personal Information",
                                    "Form",
                                ],
                                "functionality": [
                                    "Allow users to create a new account on the website",
                                    "Collect personal information from users",
                                    "Validate user-provided information",
                                    "Enable password-based authentication",
                                    "Provide options for gender selection",
                                    "Submit the registration form to create an account",
                                ],
                                "media_files_description": None,
                                "key_words": [
                                    "registration",
                                    "account creation",
                                    "new account",
                                    "personal information",
                                    "first name",
                                    "last name",
                                    "email",
                                    "password",
                                    "confirm password",
                                    "gender",
                                    "password-based authentication",
                                    "register",
                                ],
                                "relevant_fields": [
                                    {
                                        "type": "input",
                                        "attributes": ["type", "id", "placeholder"],
                                    }
                                ],
                                "curiosities": None,
                                "accessibility": [
                                    "Provision for screen readers to read the placeholder text",
                                    "Labels for form fields for better understanding",
                                    "Radio buttons for gender selection for better accessibility",
                                ],
                            },
                            "children": [],
                        },
                        {
                            "tag": "footer",
                            "size": 2301,
                            "analysis": {
                                "one_phrase_summary": "The footer contains information about jobs and the online Itsourcecode Portal Jobs System.",
                                "summary": "The footer section provides a detailed explanation of what a job is and the various ways a person "
                                "can begin a job. It also mentions the Online Itsourcecode Portal Jobs System for the year 2021.",
                                "categories": [
                                    "Jobs",
                                    "Employment",
                                    "Work",
                                    "Occupation",
                                    "Society",
                                    "Career",
                                ],
                                "functionality": [
                                    "Inform users about the concept of jobs and employment",
                                    "Explain the different ways a person can start a job",
                                    "Provide information about the Online Itsourcecode Portal Jobs System",
                                ],
                                "media_files_description": None,
                                "key_words": [
                                    "job",
                                    "employment",
                                    "work",
                                    "occupation",
                                    "society",
                                    "activity",
                                    "payment",
                                    "volunteering",
                                    "business",
                                    "parent",
                                    "Online Itsourcecode Portal Jobs System",
                                ],
                                "relevant_fields": None,
                                "curiosities": None,
                                "accessibility": None,
                            },
                            "children": [],
                        },
                    ],
                    "web_summary": {
                        "one_phrase_summary": "The website provides a platform for job seekers and employers to connect, with features for" " job registration, account creation, and navigation.",
                        "summary": "The analyzed web page is a job portal system that allows job seekers to search for and register jobs, and"
                        " employers to post job listings. It includes a registration form for users to create new accounts and provides"
                        " navigation links to different sections of the site.",
                        "categories": [
                            "Jobs",
                            "Employment",
                            "Career",
                            "Online Portals",
                            "Human Resources",
                        ],
                        "functionality": [
                            "Job seekers can search and register for jobs",
                            "Employers can post job listings",
                            "Users can create accounts to apply for jobs",
                            "Navigation to different sections of the website",
                        ],
                        "media_files_description": None,
                        "key_words": [
                            "job",
                            "employment",
                            "registration",
                            "account creation",
                            "navigation",
                            "job portal",
                            "job listings",
                            "search",
                            "apply",
                            "employer",
                            "job seeker",
                        ],
                        "curiosities": None,
                        "accessibility": [
                            "Provision for screen readers to read placeholder text",
                            "Labels for form fields for better understanding",
                            "Radio buttons for gender selection for better accessibility",
                        ],
                        "user_experience": "Users can navigate to the job portal, register for an account, search for jobs, and apply for "
                        "positions. The website provides a clear structure and easy navigation to facilitate these tasks.",
                        "seo_considerations": [
                            "Use relevant keywords in headings and content to improve search rankings",
                            "Optimize images for web performance",
                            "Ensure mobile-friendliness for better search engine visibility",
                        ],
                        "additional_notes": None,
                    },
                }
            ],
            "started_time": "2024-12-17 15:54:02",
            "ended_time": "2024-12-17 16:00:00",
            "total_time": 358.2126467227936,
            "start_url": "http://localhost:8000/",
        }

    def test_pipeline_with_cache(self):
        """
        Test the pipeline with a real website to verify the complete flow.
        """
        # Save data if not already in the repository
        if not self.analysis_repository.exists({"start_url": self.data["start_url"]}):
            self.analysis_repository.save(self.data)

        # Initialize and run the pipeline
        start_url = self.data["start_url"]
        pipeline = WebAnalysisPipeline(start_url=start_url, llm_service=self.llm_service, analysis_repository=self.analysis_repository)
        result = pipeline.analyze(enable_crawl=self.enable_crawl)

        # Assertions
        self.assertIsNotNone(result, "Pipeline analysis result should not be None.")
        self.assertEqual(result.domain, self.data["domain"], "Domain mismatch.")
        self.assertGreater(len(result.analyzed_urls), 0, "No URLs analyzed.")

        # Optional: Print results for debugging
        print("Analysis results:", result)


if __name__ == "__main__":
    unittest.main()
