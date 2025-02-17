from django.conf import settings
from django.conf.urls import url
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.staticfiles.urls import staticfiles_urlpatterns
from django.shortcuts import redirect
from django.urls import include, path, re_path

#Swagger
from config.swagger import schema_view

urlpatterns = [
                    # Django Admin, use {% url 'admin:index' %}
                    path(settings.ADMIN_URL, admin.site.urls),
                    re_path('^$', lambda request: redirect('swagger/', permanent=False)),
                    path("api/", include("pythondjangocrud.apps.events.urls")),
                    path('api/v1/', include(('pythondjangocrud.urls.apis', 'api'), namespace='api')),
                    # Django Docs - Swagger
                    url(r'^swagger(?P<format>.json|.yaml)$', schema_view.without_ui(cache_timeout=0),
                        name='schema-json'),
                    url(r'^swagger/$', schema_view.with_ui('swagger', cache_timeout=0), name='schema-swagger-ui'),
                    url(r'^redoc/$', schema_view.with_ui('redoc', cache_timeout=0), name='schema-redoc'),
                    # Your stuff: custom urls includes go here
                ] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

if settings.DEBUG:
    # Static file serving when using Gunicorn + Uvicorn for local web socket development
    urlpatterns += staticfiles_urlpatterns()

if settings.DEBUG:
    if "debug_toolbar" in settings.INSTALLED_APPS:
        import debug_toolbar

        urlpatterns = [path("__debug__/", include(debug_toolbar.urls))] + urlpatterns
