from autoppia_iwa.src.data_generation.domain.tests_classes import CheckEventEmittedTest, FindInHtmlTest
from autoppia_iwa.src.data_generation.domain.classes import BrowserSpecification
from autoppia_iwa.src.web_agents.classes import Task


TASK_EXAMPLES = [
    # Task(
    #     prompt="Get the interactive elements from the services by using strictly the 'get_dropdown_options' option only",
    #     url='https://www.w3schools.com/',
    #     specifications=BrowserSpecification(viewport_width=1920, viewport_height=1080, screen_width=1920, screen_height=1080, device_pixel_ratio=1.0, scroll_x=0, scroll_y=0, browser_x=0, browser_y=0),
    #     tests=[CheckPageViewEventTest(page_view_url='/login'), FindInHtmlTest(description='Find keywords in the current HTML content', test_type='frontend', keywords=['login', 'log in'])],
    #     milestones=None,
    #     web_analysis=None,
    # ), # ONLY for testing as it throws errors due to service not found
    # Task(
    #     prompt="Click the 'Login' button to access the login page.",
    #     url='http://localhost:8000',
    #     specifications=BrowserSpecification(viewport_width=1920, viewport_height=1080, screen_width=1920, screen_height=1080, device_pixel_ratio=1.0, scroll_x=0, scroll_y=0, browser_x=0, browser_y=0),
    #     tests=[CheckPageViewEventTest(page_view_url='/login'), FindInHtmlTest(description='Find keywords in the current HTML content', test_type='frontend', keywords=['login', 'log in'])],
    #     milestones=None,
    #     web_analysis=None,
    # ),
    Task(
        prompt="Enter your email and password in the respective fields and click the 'Log in' button to authenticate and access your account. Email:test@test.com, password:test@test.com",
        url='http://localhost:8000',
        specifications=BrowserSpecification(viewport_width=1920, viewport_height=1080, screen_width=1920, screen_height=1080, device_pixel_ratio=1.0, scroll_x=0, scroll_y=0, browser_x=0, browser_y=0),
        tests=[
            CheckEventEmittedTest(description='Verify if the backend emitted the specified event', test_type='backend', event_name='login'),
            FindInHtmlTest(description='Find keywords in the current HTML content', test_type='frontend', keywords=['logout', 'sign out', 'welcome']),
        ],
        milestones=None,
        web_analysis=None,
    ),
    # Task(
    #     prompt="Click the 'Register' dropdown in the navigation bar and select 'Employee' to register as an employee on the website.",
    #     url='http://localhost:8000',
    #     specifications=BrowserSpecification(viewport_width=1920, viewport_height=1080, screen_width=1920, screen_height=1080, device_pixel_ratio=1.0, scroll_x=0, scroll_y=0, browser_x=0, browser_y=0),
    #     tests=[
    #         CheckEventEmittedTest(description='Verify if the backend emitted the specified event', test_type='backend', event_name='registration'),
    #         FindInHtmlTest(description='Find keywords in the current HTML content', test_type='frontend', keywords=['thank you', 'registration successful', 'welcome aboard']),
    #     ],
    #     milestones=None,
    #     web_analysis=None,
    # ),
    Task(
        prompt="Navigate to the 'About Us' section by clicking on the 'About Us' link in the header menu.",
        url='http://localhost:8000',
        specifications=BrowserSpecification(viewport_width=1920, viewport_height=1080, screen_width=1920, screen_height=1080, device_pixel_ratio=1.0, scroll_x=0, scroll_y=0, browser_x=0, browser_y=0),
        tests=[],
        milestones=None,
        web_analysis=None,
    ),
    # Task(
    #     prompt='Fill out the contact form by entering your name, email, and message, then submit the form to send your inquiry.',
    #     url='http://localhost:8000',
    #     specifications=BrowserSpecification(viewport_width=1920, viewport_height=1080, screen_width=1920, screen_height=1080, device_pixel_ratio=1.0, scroll_x=0, scroll_y=0, browser_x=0, browser_y=0),
    #     tests=[
    #         CheckEventEmittedTest(description='Verify if the backend emitted the specified event', test_type='backend', event_name='message_sent'),
    #         FindInHtmlTest(description='Find keywords in the current HTML content', test_type='frontend', keywords=['thank you', 'message sent', 'inquiry received']),
    #     ],
    #     milestones=None,
    #     web_analysis=None,
    # ),
    # Task(
    #     prompt="Click the 'Register' button in the navigation menu and then select 'Employers' to access the employer registration form.",
    #     url='http://localhost:8000',
    #     specifications=BrowserSpecification(viewport_width=1920, viewport_height=1080, screen_width=1920, screen_height=1080, device_pixel_ratio=1.0, scroll_x=0, scroll_y=0, browser_x=0, browser_y=0),
    #     tests=[
    #         CheckEventEmittedTest(description='Verify if the backend emitted the specified event', test_type='backend', event_name='registration'),
    #         FindInHtmlTest(
    #             description='Find keywords in the current HTML content',
    #             test_type='frontend',
    #             keywords=['new account', 'company name', 'company address', 'email', 'password', 'confirm password', 'register'],
    #         ),
    #     ],
    #     milestones=None,
    #     web_analysis=None,
    # ),
    # Task(
    #     prompt="Click the 'Register' button in the navigation menu to open the employee registration form.",
    #     url='http://localhost:8000',
    #     specifications=BrowserSpecification(viewport_width=1920, viewport_height=1080, screen_width=1920, screen_height=1080, device_pixel_ratio=1.0, scroll_x=0, scroll_y=0, browser_x=0, browser_y=0),
    #     tests=[
    #         CheckEventEmittedTest(description='Verify if the backend emitted the specified event', test_type='backend', event_name='registration'),
    #         FindInHtmlTest(description='Find keywords in the current HTML content', test_type='frontend', keywords=['thank you', 'registration successful', 'welcome aboard']),
    #     ],
    #     milestones=None,
    #     web_analysis=None,
    # ),
    # Task(
    #     prompt="Click the 'Login' button to access the login page.",
    #     url='http://localhost:8000',
    #     specifications=BrowserSpecification(viewport_width=1920, viewport_height=1080, screen_width=1920, screen_height=1080, device_pixel_ratio=1.0, scroll_x=0, scroll_y=0, browser_x=0, browser_y=0),
    #     tests=[],
    #     milestones=None,
    #     web_analysis=None,
    # ),
    # Task(
    #     prompt="Click the 'Register' dropdown in the navigation bar and select 'Employee' to register as an employee on the website.",
    #     url='http://localhost:8000',
    #     specifications=BrowserSpecification(viewport_width=1920, viewport_height=1080, screen_width=1920, screen_height=1080, device_pixel_ratio=1.0, scroll_x=0, scroll_y=0, browser_x=0, browser_y=0),
    #     tests=[
    #         CheckEventEmittedTest(description='Verify if the backend emitted the specified event', test_type='backend', event_name='registration'),
    #         FindInHtmlTest(description='Find keywords in the current HTML content', test_type='frontend', keywords=['thank you', 'registration successful', 'welcome aboard']),
    #     ],
    #     milestones=None,
    #     web_analysis=None,
    # ),
    # Task(
    #     prompt="Navigate to the 'About Us' section by clicking on the 'About Us' link in the header menu.",
    #     url='http://localhost:8000',
    #     specifications=BrowserSpecification(viewport_width=1920, viewport_height=1080, screen_width=1920, screen_height=1080, device_pixel_ratio=1.0, scroll_x=0, scroll_y=0, browser_x=0, browser_y=0),
    #     tests=[],
    #     milestones=None,
    #     web_analysis=None,
    # ),
    # Task(
    #     prompt='Fill out the contact form by entering your name, email, and message, then submit the form to send your inquiry.',
    #     url='http://localhost:8000',
    #     specifications=BrowserSpecification(viewport_width=1920, viewport_height=1080, screen_width=1920, screen_height=1080, device_pixel_ratio=1.0, scroll_x=0, scroll_y=0, browser_x=0, browser_y=0),
    #     tests=[
    #         CheckEventEmittedTest(description='Verify if the backend emitted the specified event', test_type='backend', event_name='message_sent'),
    #         FindInHtmlTest(description='Find keywords in the current HTML content', test_type='frontend', keywords=['thank you', 'message sent', 'inquiry received']),
    #     ],
    #     milestones=None,
    #     web_analysis=None,
    # ),
    # Task(
    #     prompt="Click the 'Register' button in the navigation menu and then select 'Employers' to access the employer registration form.",
    #     url='http://localhost:8000',
    #     specifications=BrowserSpecification(viewport_width=1920, viewport_height=1080, screen_width=1920, screen_height=1080, device_pixel_ratio=1.0, scroll_x=0, scroll_y=0, browser_x=0, browser_y=0),
    #     tests=[
    #         CheckEventEmittedTest(description='Verify if the backend emitted the specified event', test_type='backend', event_name='registration'),
    #         FindInHtmlTest(
    #             description='Find keywords in the current HTML content',
    #             test_type='frontend',
    #             keywords=['new account', 'company name', 'company address', 'email', 'password', 'confirm password', 'register'],
    #         ),
    #     ],
    #     milestones=None,
    #     web_analysis=None,
    # ),
    # Task(
    #     prompt="Click the 'Register' button in the navigation menu to open the employee registration form.",
    #     url='http://localhost:8000',
    #     specifications=BrowserSpecification(viewport_width=1920, viewport_height=1080, screen_width=1920, screen_height=1080, device_pixel_ratio=1.0, scroll_x=0, scroll_y=0, browser_x=0, browser_y=0),
    #     tests=[
    #         CheckEventEmittedTest(description='Verify if the backend emitted the specified event', test_type='backend', event_name='registration'),
    #         FindInHtmlTest(description='Find keywords in the current HTML content', test_type='frontend', keywords=['thank you', 'registration successful', 'welcome aboard']),
    #     ],
    #     milestones=None,
    #     web_analysis=None,
    # ),
    # Task(
    #     prompt="Click the 'Login' button to access the login page.",
    #     url='http://localhost:8000',
    #     specifications=BrowserSpecification(viewport_width=1920, viewport_height=1080, screen_width=1920, screen_height=1080, device_pixel_ratio=1.0, scroll_x=0, scroll_y=0, browser_x=0, browser_y=0),
    #     tests=[],
    #     milestones=None,
    #     web_analysis=None,
    # ),
]
