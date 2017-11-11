from django.core.management.base import BaseCommand
import click
import re
from games.models import (Personality, PersonalityUrl, PersonalityAlias)


class Cluster:
    def __init__(self, personality=None):
        self.pers = []
        self.id_to_local = dict()  # for alias
        self.local_to_id = []  # for alias
        self.urlid_to_count = dict()
        self.urlids = set()

        if personality:
            self.pers.append(personality)

            for x in personality.personalityurl_set.all():
                self.urlids.add(x.url.id)

            for x in self.urlids:
                self.urlid_to_count[x] = 1

            for x in personality.personalityalias_set.all():
                if x.id in self.id_to_local:
                    continue
                loc = len(self.local_to_id)
                self.id_to_local[x.id] = loc
                self.local_to_id.append(x.id)

    def Intersects(self, other):
        return not self.urlids.isdisjoint(other.urlids)

    def Merge(self, other):
        self.pers.extend(other.pers)
        self.urlids.update(other.urlids)
        for k, v in other.urlid_to_count.items():
            self.urlid_to_count[k] = self.urlid_to_count.get(k, 0) + v
        for x in other.local_to_id:
            if x in self.id_to_local:
                continue
            loc = len(self.local_to_id)
            self.id_to_local[x] = loc
            self.local_to_id.append(x)

    def Print(self):
        for i, p in enumerate(self.pers):
            click.secho("[%d] %d: %s" % (i, p.id, p.name[:60]), fg='yellow')
            for u in p.personalityurl_set.all():
                click.secho(
                    "   %d: %s" % (u.url.id, u.url.original_url[:250]),
                    fg='red',
                    bold=(self.urlid_to_count[u.url.id] > 1))

            for u in p.personalityalias_set.all():
                var = ''
                if u.is_blacklisted:
                    var += click.style(' (blacklisted)', fg='green', bold=True)

                if u.hidden_for:
                    var += click.style(
                        ' (%d)' % u.hidden_for.id, fg='yellow', bold=True)

                click.secho(
                    "   [%d] %d (%d): %s%s" %
                    (self.id_to_local[u.id], u.id, len(u.gameauthor_set.all()),
                     u.name, var),
                    fg='green')

    def Size(self):
        return len(self.pers)

    def GetAlias(self, id):
        return PersonalityAlias.objects.get(pk=self.local_to_id[int(id)])


def TrySimplifyCluster(cluster, idx):
    while True:
        w = cluster[idx]
        for i, x in enumerate(cluster):
            if i == idx:
                continue
            if x.Intersects(w):
                x.Merge(w)
                del cluster[idx]
                idx = i if i < idx else i - 1
                break
        else:
            return


def MergePerson(frm, to):
    to = Personality.objects.get(pk=to.pk)
    if frm.bio and (to.bio is None or len(to.bio) < len(frm.bio)):
        to.bio = frm.bio
        to.save()

    existing = set()
    for x in to.personalityurl_set.all():
        existing.add(x.url.id)

    for x in frm.personalityurl_set.all():
        if x.url.id in existing:
            x.delete()
        else:
            existing.add(x.url.id)
            x.personality = to
            x.save()

    for x in frm.personalityalias_set.all():
        x.personality = to
        x.save()


class Command(BaseCommand):
    help = 'Fixes authors.'

    def handle(self, *args, **options):
        click.secho("Building clusters...", fg='red')

        clusters = []

        for p in Personality.objects.all().prefetch_related(
                'personalityurl_set', 'personalityalias_set'):
            clusters.append(Cluster(p))
            TrySimplifyCluster(clusters, len(clusters) - 1)

        clusters.sort(key=lambda x: x.Size(), reverse=True)
        click.clear()
        for c in clusters:
            clsr = c
            while True:
                clsr.Print()
                inp = click.prompt('', prompt_suffix='help >>>>>>>>>>>>>> ')
                click.clear()
                if inp == 'help':
                    click.secho('  n next', fg='blue')
                    click.secho('  p1+4 merge Person 4 into 1', fg='blue')
                    click.secho('  pa1 merge all persons into 1', fg='blue')
                    click.secho(
                        '  p1n ASDF set persons 1 name ASDF', fg='blue')
                    click.secho(
                        '  a1nf For persn 1 name "First Last" -> "Last, First"',
                        fg='blue')
                    click.secho(
                        '  p1nfa2 set persons 1 name from alias 2', fg='blue')
                    click.secho('  p1u2d delete url 2 for person 1', fg='blue')
                    click.secho(
                        '  p1n2 person 1 take name from alias 2', fg='blue')
                    click.secho('  a1b blacklist alias 1', fg='blue')
                    click.secho('  a1w whitelist alias 1', fg='blue')
                    click.secho('  a1n ASDF set alias 1 name ASDF', fg='blue')
                    click.secho(
                        '  a1nf For alias 1 name "Last, First" -> "First Last"',
                        fg='blue')
                    click.secho(
                        '  a1h2 hide alias 1 to 2 (must be same person)',
                        fg='blue')
                    click.secho('  a1u unhide alias 1', fg='blue')
                    click.secho('  u1d delete url 1', fg='blue')
                    continue
                if inp == 'n':
                    click.secho('Next.', fg='blue')
                    break
                m = re.match(r'p(\d+)\+(\d+)$', inp)
                if m:
                    to = int(m.group(1))
                    frm = int(m.group(2))
                    click.secho(
                        'Merge person %d into %d' % (frm, to), fg='blue')
                    MergePerson(clsr.pers[frm], clsr.pers[to])

                m = re.match(r'pa(\d+)$', inp)
                if m:
                    to = int(m.group(1))
                    click.secho('Merge all persons into %d' % to, fg='blue')
                    for i, p in enumerate(clsr.pers):
                        if i != to:
                            MergePerson(p, clsr.pers[to])

                m = re.match(r'p(\d+)nf$', inp)
                if m:
                    to = clsr.pers[int(m.group(1))]
                    m2 = re.match('(.*?) (.*)$', to.name)
                    if m2:
                        toname = "%s, %s" % (m2.group(2), m2.group(1))
                        click.secho(
                            'Set persons %s name into [%s]' % (m.group(1),
                                                               toname),
                            fg='blue')
                        if Personality.objects.filter(name=toname).count() > 0:
                            click.secho(
                                'Personality with that name already exists!',
                                fg='red',
                                bold=True)
                        else:
                            to.name = toname
                            to.save()
                    else:
                        click.secho('Cannot parse name!', fg='red', bold=True)

                m = re.match(r'p(\d+)n (.+)$', inp)
                if m:
                    click.secho(
                        'Set persons %s name into %s' % (m.group(1),
                                                         m.group(2)),
                        fg='blue')
                    clsr.pers[int(m.group(1))].name = m.group(2)
                    clsr.pers[int(m.group(1))].save()

                m = re.match(r'p(\d+)nfa(\d+)$', inp)
                if m:
                    click.secho(
                        'Set persons %s name into %s' % (m.group(1),
                                                         m.group(2)),
                        fg='blue')
                    p = clsr.pers[int(m.group(1))]
                    x = clsr.GetAlias(m.group(2))
                    if x.personality_id == p.id:
                        p.name = x.name
                        p.save()
                    else:
                        click.secho(
                            'Personality differs, doing nothing',
                            fg='red',
                            bold=True)

                m = re.match(r'p(\d+)u(\d+)d$', inp)
                if m:
                    p = int(m.group(1))
                    u = int(m.group(2))
                    click.secho(
                        'Kill url %d from persons %d' % (u, p), fg='blue')
                    PersonalityUrl.objects.filter(
                        url_id=u, personality_id=clsr.pers[p].id).delete()

                m = re.match(r'u(\d+)d$', inp)
                if m:
                    u = int(m.group(1))
                    click.secho('Kill url %d from all persons.' % u, fg='blue')
                    for p in clsr.pers:
                        PersonalityUrl.objects.filter(
                            url_id=u, personality_id=p.id).delete()

                m = re.match(r'a(\d+)b$', inp)
                if m:
                    a = int(m.group(1))
                    click.secho('Blacklist alias %d.' % a, fg='blue')
                    x = clsr.GetAlias(a)
                    x.is_blacklisted = True
                    x.save()

                m = re.match(r'a(\d+)w$', inp)
                if m:
                    a = int(m.group(1))
                    click.secho('Whitelist alias %d.' % a, fg='blue')
                    x = clsr.GetAlias(a)
                    x.is_blacklisted = False
                    x.save()

                m = re.match(r'a(\d+)n (.+)$', inp)
                if m:
                    click.secho(
                        'Set aliases %s name into %s' % (m.group(1),
                                                         m.group(2)),
                        fg='blue')
                    if PersonalityAlias.objects.filter(
                            name=m.group(2)).count() > 0:
                        click.secho(
                            'Alias with this name already exists.',
                            fg='red',
                            bold=True)
                    else:
                        a = int(m.group(1))
                        x = clsr.GetAlias(a)
                        x.name = m.group(2)
                        x.save()

                m = re.match(r'a(\d+)nf$', inp)
                if m:
                    to = clsr.GetAlias(int(m.group(1)))
                    m2 = re.match('(.*), (.*)$', to.name)
                    if m2:
                        toname = "%s %s" % (m2.group(2), m2.group(1))
                        click.secho(
                            'Set alias %s name into [%s]' % (m.group(1),
                                                             toname),
                            fg='blue')
                        if PersonalityAlias.objects.filter(
                                name=toname).count() > 0:
                            click.secho(
                                'Alias with that name already exists!',
                                fg='red',
                                bold=True)
                        else:
                            to.name = toname
                            to.save()
                    else:
                        click.secho('Cannot parse name!', fg='red', bold=True)

                m = re.match(r'a(\d+)h(\d+)$', inp)
                if m:
                    a = int(m.group(1))
                    b = int(m.group(2))
                    click.secho('Hide alias %d to %d.' % (a, b), fg='blue')
                    x = clsr.GetAlias(a)
                    y = clsr.GetAlias(b)
                    if x.personality_id == y.personality_id:
                        x.hidden_for = y
                        x.save()
                    else:
                        click.secho(
                            'Personality differs, doing nothing',
                            fg='red',
                            bold=True)

                m = re.match(r'a(\d+)u$', inp)
                if m:
                    a = int(m.group(1))
                    click.secho('Unhide alias %d.' % a, fg='blue')
                    x = clsr.GetAlias(a)
                    x.hidden_for = None
                    x.save()

                newclsr = Cluster()
                for x in clsr.pers:
                    newclsr.Merge(Cluster(Personality.objects.get(id=x.id)))
                clsr = newclsr
