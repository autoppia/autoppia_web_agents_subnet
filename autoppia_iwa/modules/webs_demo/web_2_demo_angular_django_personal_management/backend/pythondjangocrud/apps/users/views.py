from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.messages.views import SuccessMessageMixin
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.views.generic import DetailView, RedirectView, UpdateView

from pythondjangocrud.apps.events.utils import create_event

User = get_user_model()


class UserDetailView(LoginRequiredMixin, DetailView):

    model = User
    slug_field = "username"
    slug_url_kwarg = "username"

    def get(self, request, *args, **kwargs):
        # Log the event when the user views their profile
        create_event(
            user=request.user,
            event_type='user_view',
            description=f'User {request.user.username} viewed their profile',
            data={'username': request.user.username},
            miner_id=request.headers.get("X-Miner-Id", None)
        )
        return super().get(request, *args, **kwargs)

user_detail_view = UserDetailView.as_view()


class UserUpdateView(LoginRequiredMixin, SuccessMessageMixin, UpdateView):

    model = User
    fields = ["name"]
    success_message = _("Information successfully updated")

    def get_success_url(self):
        assert (
            self.request.user.is_authenticated
        )  # for mypy to know that the user is authenticated
        return self.request.user.get_absolute_url()

    def get_object(self):
        return self.request.user

    def form_valid(self, form):
        # Log the event when the user updates their information
        response = super().form_valid(form)
        create_event(
            user=self.request.user,
            event_type='user_update',
            description=f'User {self.request.user.username} updated their profile',
            data={'username': self.request.user.username, 'name': form.cleaned_data['name']},
            miner_id=self.request.headers.get("X-Miner-Id", None)
        )
        return response

user_update_view = UserUpdateView.as_view()


class UserRedirectView(LoginRequiredMixin, RedirectView):

    permanent = False

    def get_redirect_url(self):
        # Log the event when the user is redirected
        create_event(
            user=self.request.user,
            event_type='user_redirect',
            description=f'User {self.request.user.username} was redirected to their profile',
            data={'username': self.request.user.username},
            miner_id=self.request.headers.get("X-Miner-Id", None)
        )
        return reverse("users:detail", kwargs={"username": self.request.user.username})


user_redirect_view = UserRedirectView.as_view()
