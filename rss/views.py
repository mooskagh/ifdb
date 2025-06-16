from django.contrib.sites.shortcuts import get_current_site
from django.http import HttpResponse
from django.urls import reverse
from django.utils.feedgenerator import Rss201rev2Feed

from core.snippets import LastComments


def comments(request, jam_id=None):
    site = get_current_site(request).domain
    url = "https://%s" % site

    fg = Rss201rev2Feed(
        title="%s ⁠— комментарии" % site,
        link=url,
        description="Комментарии на сайте %s" % site,
    )

    for x in LastComments(event=jam_id, days=90, limit=100):
        fg.add_item(
            title=x.game.title,
            link="%s%s"
            % (url, reverse("show_game", kwargs={"game_id": x.game.id})),
            description=x.text,
            author_name=x.GetUsername(),
            pubdate=x.creation_time,
            unique_id="/gamecomment/%d" % (x.id),
        )

    return HttpResponse(
        fg.writeString("utf-8"), content_type="application/rss+xml"
    )
