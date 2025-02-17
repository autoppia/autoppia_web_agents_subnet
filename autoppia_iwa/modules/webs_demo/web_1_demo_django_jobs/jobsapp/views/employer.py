from django.contrib.auth.decorators import login_required
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.urls import reverse_lazy
from django.utils.decorators import method_decorator
from django.views.generic import CreateView, ListView

from events.utils import create_event
from jobsapp.decorators import user_is_employer
from jobsapp.forms import CreateJobForm
from jobsapp.models import Job, Applicant


@method_decorator([login_required(login_url=reverse_lazy('accounts:login')), user_is_employer], name='dispatch')
class DashboardView(ListView):
    model = Job
    template_name = 'jobs/employer/dashboard.html'
    context_object_name = 'jobs'

    def get_queryset(self):
        return self.model.objects.filter(user_id=self.request.user.id)


@method_decorator([login_required(login_url=reverse_lazy('accounts:login')), user_is_employer], name='dispatch')
class ApplicantPerJobView(ListView):
    model = Applicant
    template_name = 'jobs/employer/applicants.html'
    context_object_name = 'applicants'
    paginate_by = 10

    def get_queryset(self):
        return Applicant.objects.filter(job_id=self.kwargs['job_id']).order_by('id')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['job'] = get_object_or_404(Job, id=self.kwargs['job_id'])
        return context


@method_decorator(login_required(login_url=reverse_lazy('accounts:login')), name='dispatch')
class JobCreateView(CreateView):
    template_name = 'jobs/create.html'
    form_class = CreateJobForm
    extra_context = {
        'title': 'Post New Job'
    }
    success_url = reverse_lazy('jobs:employer-dashboard')

    @method_decorator(login_required(login_url=reverse_lazy('accounts:login')))
    def dispatch(self, request, *args, **kwargs):
        if not self.request.user.is_authenticated:
            return reverse_lazy('accounts:login')
        if self.request.user.is_authenticated and self.request.user.role != 'employer':
            return reverse_lazy('accounts:login')
        return super().dispatch(self.request, *args, **kwargs)

    def form_valid(self, form):
        form.instance.user = self.request.user
        response = super().form_valid(form)

        # Use the create_event utility function
        create_event(
            event_type='job_post_creation',
            description=f"Job post '{form.instance.title}' created.",
            user=self.request.user,
            data={'job_id': form.instance.id, 'title': form.instance.title},
            web_agent_id=request.headers.get("X-WebAgent-Id")
        )

        return response

    def post(self, request, *args, **kwargs):
        form = self.get_form()
        if form.is_valid():
            return self.form_valid(form)
        return self.form_invalid(form)


@method_decorator(login_required(login_url=reverse_lazy('accounts:login')), name='dispatch')
class ApplicantsListView(ListView):
    model = Applicant
    template_name = 'jobs/employer/all-applicants.html'
    context_object_name = 'applicants'

    def get_queryset(self):
        # jobs = Job.objects.filter(user_id=self.request.user.id)
        return self.model.objects.filter(job__user_id=self.request.user.id)


@login_required(login_url=reverse_lazy('accounts:login'))
def filled(request, job_id=None):
    job = get_object_or_404(Job, user_id=request.user.id, id=job_id)
    job.filled = True
    job.save()

    # Use the create_event utility function
    create_event(
        event_type='job_post_update',
        description=f"Job post '{job.title}' marked as filled.",
        user=request.user,
        data={'job_id': job.id, 'title': job.title},
        web_agent_id=request.headers.get("X-WebAgent-Id")
    )

    return HttpResponseRedirect(reverse_lazy('jobs:employer-dashboard'))
