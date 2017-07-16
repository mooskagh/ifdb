from .models import Game
from .tools import (FormatDate, FormatTime, StarsFromRating, RenderMarkdown,
                    ExtractYoutubeId)
from logging import getLogger
from statistics import mean, median
from core.packages import BuildGameUserFingerprint
from django.conf import settings

logger = getLogger('web')


def Partition(links, partitions):
    rest = []
    cats = {x: None for y in partitions for x in y}
    for x in links:
        if x['category'].symbolic_id in cats:
            cats[x['category'].symbolic_id] = x
        else:
            rest.append(x)

    res = []
    for x in partitions:
        r = []
        for y in x:
            if cats[y] and cats[y]['items']:
                for z in cats[y]['items']:
                    r.append(z)
        res.append(r)
    return res + [rest]


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
        authors, participants = Partition(self.GetAuthors(), [('author', )])
        media, online, download, links = Partition(
            self.GetURLs(), [('poster', 'video', 'screenshot'),
                             ('play_in_interpreter', 'play_online'),
                             ('download_direct', 'download_landing')])
        media = AnnotateMedia(media)
        md = RenderMarkdown(self.game.description)
        tags = self.GetTagsForDetails()
        votes = self.GetGameScore()
        comments = self.GetGameComments()
        loonchator_links = []
        for x in self.game.package_set.all():
            loonchator_links.append(
                "%s://rungame/%s" %
                (('ersatzplut-debug' if settings.DEBUG else 'ersatzplut'),
                 BuildGameUserFingerprint(self.request, x.id)))
        return {
            'edit_perm': self.request.perm(self.game.edit_perm),
            'comment_perm': self.request.perm(self.game.comment_perm),
            'delete_perm': False,
            'added_date': added_date,
            'authors': authors,
            'participants': participants,
            'game': self.game,
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
        }

    def GetAuthors(self):
        authors = {}
        roles = []
        for x in self.game.gameauthor_set.all():
            if x.role in authors:
                authors[x.role].append(x.author)
            else:
                roles.append(x.role)
                authors[x.role] = [x.author]
        roles.sort(key=lambda x: x.order)
        res = []
        for r in roles:
            res.append({'category': r, 'items': authors[r]})
        return res

    def GetURLs(self):
        urls = {}
        cats = []
        for x in self.game.gameurl_set.all():
            category = x.category
            if category in urls:
                urls[category].append(x)
            else:
                cats.append(category)
                urls[category] = [x]
        cats.sort(key=lambda x: x.order)
        res = []
        for r in cats:
            res.append({'category': r, 'items': urls[r]})
        return res

    def GetTagsForDetails(self):
        tags = {}
        cats = []
        for x in self.game.tags.all():
            category = x.category
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
        finished_votes = []
        finished_times = []
        played_votes = []
        played_times = []
        res['user_hours'] = ''
        res['user_mins'] = ''
        res['user_score'] = ''
        res['user_finished'] = False

        for v in self.game.gamevote_set.all():
            played_votes.append(v.star_rating)
            played_times.append(v.play_time_mins)
            if v.game_finished:
                finished_votes.append(v.star_rating)
                finished_times.append(v.play_time_mins)
            if v.user == user:
                res['user_played'] = True
                res['user_hours'] = v.play_time_mins // 60
                res['user_mins'] = v.play_time_mins % 60
                res['user_score'] = v.star_rating
                res['user_finished'] = v.game_finished

        res['played_count'] = len(played_votes)
        if played_votes:
            avg = mean(played_votes)
            res['avg_rating'] = ("%3.1f" % avg).replace('.', ',')
            res['stars'] = StarsFromRating(avg)

            t = round(median(played_times))
            res['played_hours'] = t // 60
            res['played_mins'] = t % 60

        res['finished_count'] = len(finished_votes)
        if finished_votes:
            t = round(median(finished_times))
            res['finished_hours'] = t // 60
            res['finished_mins'] = t % 60

        return res

    # Returns repeated:
    # user__name
    # parent__id
    #
    def GetGameComments(self):
        res = []
        for v in self.game.gamecomment_set.select_related('user'):
            res.append({
                'id':
                    v.id,
                'user_id':
                    v.user.id if v.user else None,
                'username':
                    v.user.username if v.user else v.foreign_username
                    if v.foreign_username else 'Анонимоўс',
                'parent_id':
                    v.parent.id if v.parent else None,
                'fusername':
                    v.foreign_username,
                'furl':
                    v.foreign_username,
                'fsite':
                    None,  # TODO
                'created':
                    FormatTime(v.creation_time),
                'edited':
                    FormatTime(v.edit_time),
                'subj':
                    v.subject,
                'text':
                    RenderMarkdown(v.text),
                # TODO: is_deleted
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

        clusters.sort(key=lambda x: x[0]['created'])
        for x in clusters:
            x[1:] = sorted(x[1:], key=lambda t: t['created'])

        return [x for y in clusters for x in y]
