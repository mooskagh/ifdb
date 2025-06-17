"""ifdb URL Configuration

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/1.10/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  url(r'^$', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  url(r'^$', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.conf.urls import url, include
    2. Add a URL to urlpatterns:  url(r'^blog/', include('blog.urls'))
"""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.http.response import HttpResponseRedirect
from django.urls import include, re_path

urlpatterns = [
    re_path(r"^$", lambda r: HttpResponseRedirect("index/")),
    re_path(r"^adminz/", admin.site.urls, name="admin"),
    # Redirect old docs URLs to home page
    re_path(r"^docs/.*", lambda r: HttpResponseRedirect("/")),
    re_path(r"^", include("core.urls"), name="api"),
    re_path(r"^", include("games.urls"), name="games"),
    re_path(r"^", include("moder.urls"), name="moder"),
    re_path(r"^jam/", include("contest.urls"), name="contest"),
    re_path(r"^rss/", include("rss.urls"), name="rss"),
]

if settings.DEBUG:
    urlpatterns = (
        static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
        + urlpatterns
    )
