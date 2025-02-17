from django.contrib import messages, auth
from django.http import HttpResponseRedirect
from django.shortcuts import render, redirect
from django.urls import reverse_lazy
from django.views.generic import CreateView, FormView, RedirectView

from accounts.forms import EmployeeRegistrationForm, EmployerRegistrationForm, UserLoginForm
from accounts.models import User
from events.utils import create_event


class BaseRegistrationView(CreateView):
    model = User
    success_url = reverse_lazy('accounts:login')
    extra_context = {'title': 'Register'}

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect(self.success_url)
        return super().dispatch(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        form = self.form_class(request.POST)

        if form.is_valid():
            user = form.save(commit=False)
            user.set_password(form.cleaned_data.get("password1"))
            user.save()
            web_agent_id = request.headers.get("X-WebAgent-Id")
            create_event(user=user, event_type='registration', description=f'{user.role.capitalize()} registered', web_agent_id=web_agent_id)
            self.post_event(user)
            return redirect(self.success_url)
        return render(request, self.template_name, {'form': form})

    def post_event(self, user):
        """To be overridden by subclasses for additional event creation if needed."""
        pass


class RegisterEmployeeView(BaseRegistrationView):
    form_class = EmployeeRegistrationForm
    template_name = 'accounts/employee/register.html'

    def post_event(self, user):
        web_agent_id = self.request.headers.get("X-WebAgent-Id")
        create_event(user=user, event_type='profile_update', description='Employee profile created', web_agent_id=web_agent_id)


class RegisterEmployerView(BaseRegistrationView):
    form_class = EmployerRegistrationForm
    template_name = 'accounts/employer/register.html'

    def post_event(self, user):
        web_agent_id = self.request.headers.get("X-WebAgent-Id")
        create_event(user=user, event_type='profile_update', description='Employer profile created', web_agent_id=web_agent_id)


class LoginView(FormView):
    """
    Provides the ability to login as a user with an email and password.
    """
    success_url = '/'
    form_class = UserLoginForm
    template_name = 'accounts/login.html'
    extra_context = {'title': 'Login'}

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return HttpResponseRedirect(self.get_success_url())
        return super().dispatch(request, *args, **kwargs)

    def get_success_url(self):
        return self.request.GET.get('next', self.success_url)

    def get_form_class(self):
        return self.form_class

    def form_valid(self, form):
        user = form.get_user()
        auth.login(self.request, user)

        web_agent_id = self.request.headers.get("X-WebAgent-Id")
        create_event(user=user, event_type='login', description=f'User logged in with email {user.email}', web_agent_id=web_agent_id)
        return HttpResponseRedirect(self.get_success_url())

    def form_invalid(self, form):
        """If the form is invalid, render the invalid form."""
        return self.render_to_response(self.get_context_data(form=form))


class LogoutView(RedirectView):
    """
    Provides users the ability to logout.
    """
    url = '/login'

    def get(self, request, *args, **kwargs):
        web_agent_id = request.headers.get("X-WebAgent-Id")
        create_event(user=request.user, event_type='logout', description='User logged out', web_agent_id=web_agent_id)
        auth.logout(request)
        messages.success(request, 'You are now logged out')
        return super().get(request, *args, **kwargs)
