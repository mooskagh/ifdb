from .models import Game
from .tools import (FormatDate, FormatTime, StarsFromRating, RenderMarkdown,
                    ExtractYoutubeId, PartitionItems)
from .search import BaseXWriter
from contest.models import GameListEntry
from contest.views import FormatHead
from core.views import BuildPackageUserFingerprint
from django.conf import settings
from django.urls import reverse
from logging import getLogger
from statistics import mean
from moder.actions import GetModerActions
import json

logger = getLogger('web')


def AnnotateMedia(media):
    res = []
    media.sort(key=lambda x: x.description)
    for y in media:
        val = {}
        if y.category.symbolic_id in ['poster', 'screenshot']:
            val['type'] = 'img'
            val['img'] = y.GetLocalUrl()
        elif y.category.symbolic_id == 'video':
            idd = ExtractYoutubeId(y.url.original_url)
            if idd:
                val['type'] = 'youtube'
                val['id'] = idd
            else:
                logger.error('Unknown video url: %s' % y.url.original_url)
                val['type'] = 'unknown'
                val['url'] = y.GetLocalUrl()
        else:
            logger.error('Unexpected category: %s' % y)
            continue
        res.append(val)
    return res


class GameDetailsBuilder:
    def __init__(self, game_id, request):
        self.game = Game.objects.prefetch_related(
            'gameauthor_set__role', 'gameauthor_set__author',
            'gameurl_set__category', 'gameurl_set__url',
            'tags__category').select_related().get(id=game_id)
        self.request = request
        request.perm.Ensure(self.game.view_perm)

    def GetGameDict(self):
        release_date = FormatDate(self.game.release_date)
        last_edit_date = FormatDate(self.game.edit_time)
        added_date = FormatDate(self.game.creation_time)
        authors, participants = PartitionItems(
            self.game.gameauthor_set.all(), [('author', )],
            catfield='role',
            follow='author')
        media, online, download, links = PartitionItems(
            self.game.gameurl_set.all(),
            [('poster', 'video', 'screenshot'),
             ('play_in_interpreter', 'play_online'),
             ('download_direct', 'download_landing')])
        media = AnnotateMedia(media)
        md = RenderMarkdown(self.game.description)
        tags = self.GetTagsForDetails()
        votes = self.GetGameScore()
        comments = self.GetGameComments()
        competitions = self.GetCompetitions()
        loonchator_links = []
        for x in self.game.package_set.all():
            loonchator_links.append(
                "%s://rungame/%s" %
                (('ersatzplut-debug' if settings.DEBUG else 'ersatzplut'),
                 BuildPackageUserFingerprint(
                     self.request.user
                     if self.request.user.is_authenticated else None, x.id)))
        return {
            'comment_perm': self.request.perm(self.game.comment_perm),
            'vote_perm': self.request.perm(self.game.vote_perm),
            'added_date': added_date,
            'authors': authors,
            'participants': participants,
            'game': self.game,
            'moder_actions': GetModerActions(self.request, 'Game', self.game),
            'last_edit_date': last_edit_date,
            'markdown': md,
            'release_date': release_date,
            'tags': tags,
            'links': links,
            'media': media,
            'online': online,
            'download': download,
            'votes': votes,
            'comments': comments,
            'loonchator_links': loonchator_links,
            'competitions': competitions,
        }

    def GetCompetitions(self):
        comps = GameListEntry.objects.filter(
            game=self.game,
            gamelist__competition__isnull=False).select_related(
                'gamelist', 'gamelist__competition')
        res = []
        for x in comps:
            opts = json.loads(x.gamelist.competition.options)
            item = {
                'slug': x.gamelist.competition.slug,
                'title': x.gamelist.competition.title,
                'nomination': x.gamelist.title,
                'head': FormatHead(x, opts),
            }

            res.append(item)
        return res

    def GetTagsForDetails(self):
        tags = {}
        cats = []
        for x in self.game.tags.all():
            category = x.category
            writer = BaseXWriter()
            writer.addHeader(2, category.id)
            writer.addSet([x.id])
            x.search_query = "%s?q=%s" % (reverse('list_games'),
                                          writer.GetStr())
            if not self.request.perm(category.show_in_details_perm):
                continue
            if category in tags:
                tags[category].append(x)
            else:
                cats.append(category)
                tags[category] = [x]
        cats.sort(key=lambda x: x.order)
        res = []
        for r in cats:
            res.append({'category': r, 'items': tags[r]})
        return res

    ################################################
    # Returns:
    # - avg_rating
    # - stars[5]
    # - played_count
    # - finished_count
    # - played_hours
    # - played_mins
    # - finished_hours
    # - finished_mins
    # - user_played
    # - user_hours
    # - user_mins
    # - user_score
    def GetGameScore(self):
        user = self.request.user
        res = {'user_played': False}
        if user and not user.is_authenticated:
            user = None
        played_votes = []
        res['user_hours'] = ''

        for v in self.game.gamevote_set.all():
            played_votes.append(v.star_rating)
            if v.user == user:
                res['user_played'] = True
                res['user_score'] = v.star_rating

        res['played_count'] = len(played_votes)
        if played_votes:
            avg = mean(played_votes)
            res['avg_rating'] = ("%3.1f" % avg).replace('.', ',')
            res['stars'] = StarsFromRating(avg)

        return res

    # Returns repeated:
    # user__name
    # parent__id
    #
    def GetGameComments(self):
        res = []
        for v in self.game.gamecomment_set.select_related('user'):
            res.append({
                'id': v.id,
                'user_id': v.user.id if v.user else None,
                'username': v.GetUsername(),
                'parent_id': v.parent.id if v.parent else None,
                'created': FormatTime(v.creation_time),
                'created_raw': v.creation_time,
                'edited': FormatTime(v.edit_time),
                'text': RenderMarkdown(v.text),
                'is_deleted': v.is_deleted,
            })

        parent_to_cluster = {}
        clusters = []

        while res:
            swap = []
            for v in res:
                if not v['parent_id']:
                    parent_to_cluster[v['id']] = len(clusters)
                    clusters.append([v])
                elif v['parent_id'] in parent_to_cluster:
                    clusters[parent_to_cluster[v['parent_id']]].append(v)
                    parent_to_cluster[v['id']] = parent_to_cluster[v[
                        'parent_id']]
                else:
                    swap.append(v)
            res = swap

        clusters.sort(key=lambda x: x[0]['created_raw'])
        for x in clusters:
            x[1:] = sorted(x[1:], key=lambda t: t['created_raw'])

        return [x for y in clusters for x in y]
