from django.conf.urls import url
from . import views

urlpatterns = [
    url(r'^api/v0/fetchpackage$', views.fetchpackage, name='fetchpackage'),
    url(r'^api/v0/logtime$', views.logtime, name='logtime'),
    url(r'^docs/(?P<slug>[-\w]+)', views.showdoc, name='showdoc'),
]
