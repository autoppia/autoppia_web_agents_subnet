from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse_lazy
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.generic import ListView, DetailView, CreateView, View, TemplateView

from events.utils import create_event
from jobsapp.forms import ApplyJobForm, ContactForm
from jobsapp.models import Job, Applicant


class HomeView(ListView):
    model = Job
    template_name = 'home.html'
    context_object_name = 'jobs'

    def get_queryset(self):
        return self.model.objects.all()[:6]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['trendings'] = self.model.objects.filter(created_at__month=timezone.now().month)[:3]

        # Log event for home page view
        if self.request.user.is_authenticated:
            create_event(
                event_type='page_view',
                description='User viewed the home page.',
                user=self.request.user,
                data={'trendings_count': context['trendings'].count()},
                web_agent_id=self.request.headers.get("X-WebAgent-Id")
            )
        return context


class SearchView(ListView):
    model = Job
    template_name = 'jobs/search.html'
    context_object_name = 'jobs'

    def get_queryset(self):
        location = self.request.GET.get('location', '')
        position = self.request.GET.get('position', '')
        queryset = self.model.objects.filter(location__icontains=location, title__icontains=position)

        # Log event for search
        if self.request.user.is_authenticated:
            create_event(
                event_type='search',
                description=f"User searched for jobs in '{location}' for position '{position}'.",
                user=self.request.user,
                data={'location': location, 'position': position, 'results_count': queryset.count()},
                web_agent_id=self.request.headers.get("X-WebAgent-Id")
            )
        return queryset


class JobListView(ListView):
    model = Job
    template_name = 'jobs/jobs.html'
    context_object_name = 'jobs'
    paginate_by = 5

    def get_queryset(self):
        queryset = super().get_queryset()

        # Log event for job list view
        if self.request.user.is_authenticated:
            create_event(
                event_type='page_view',
                description='User viewed the job list page.',
                user=self.request.user,
                data={'jobs_count': queryset.count()},
                web_agent_id=self.request.headers.get("X-WebAgent-Id")
            )
        return queryset


class JobDetailsView(DetailView):
    model = Job
    template_name = 'jobs/details.html'
    context_object_name = 'job'
    pk_url_kwarg = 'id'

    def get_object(self, queryset=None):
        obj = super(JobDetailsView, self).get_object(queryset=queryset)
        if obj is None:
            raise Http404("Job doesn't exist")
        return obj

    def get(self, request, *args, **kwargs):
        try:
            self.object = self.get_object()
        except Http404:
            raise Http404("Job doesn't exist")

        context = self.get_context_data(object=self.object)

        # Log event for job detail view
        if self.request.user.is_authenticated:
            create_event(
                event_type='page_view',
                description=f"User viewed job details for '{self.object.title}'.",
                user=self.request.user,
                data={'job_id': self.object.id, 'title': self.object.title},
                web_agent_id=self.request.headers.get("X-WebAgent-Id")
            )

        return self.render_to_response(context)


@method_decorator(login_required(login_url=reverse_lazy('accounts:login')), name='dispatch')
class ApplyJobView(CreateView):
    model = Applicant
    form_class = ApplyJobForm
    slug_field = 'job_id'
    slug_url_kwarg = 'job_id'

    def post(self, request, *args, **kwargs):
        form = self.get_form()
        if form.is_valid():
            messages.info(self.request, 'Successfully applied for the job!')
            return self.form_valid(form)
        else:
            return HttpResponseRedirect(reverse_lazy('jobs:home'))

    def get_success_url(self):
        return reverse_lazy('jobs:jobs-detail', kwargs={'id': self.kwargs['job_id']})

    # def get_form_kwargs(self):
    #     kwargs = super(ApplyJobView, self).get_form_kwargs()
    #     print(kwargs)
    #     kwargs['job'] = 1
    #     return kwargs

    def form_valid(self, form):
        # Check if user already applied
        applicant = Applicant.objects.filter(user_id=self.request.user.id, job_id=self.kwargs['job_id'])
        if applicant.exists():
            messages.info(self.request, 'You already applied for this job')
            return HttpResponseRedirect(self.get_success_url())

        # Save applicant
        form.instance.user = self.request.user
        form.save()

        # Log event for job application
        create_event(
            event_type='job_application',
            description=f"User applied for job '{form.instance.job.title}'.",
            user=self.request.user,
            data={'job_id': form.instance.job.id, 'applicant_id': form.instance.id},
            web_agent_id=self.request.headers.get("X-WebAgent-Id")
        )

        return super().form_valid(form)


class ContactView(View):
    def get(self, request):
        form = ContactForm()
        return render(request, 'jobs/contact.html', {'form': form})

    def post(self, request):
        form = ContactForm(request.POST)
        if form.is_valid():
            # Process the form data
            form.save()
            return render(request, 'jobs/contact.html', {'form': form, 'success': True})
        return render(request, 'jobs/contact.html', {'form': form})


class AboutView(TemplateView):
    template_name = "jobs/about.html"
