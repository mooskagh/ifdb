import re
from logging import getLogger

from dateutil.parser import parse as parse_date
from django.utils import timezone

from core.taskqueue import Enqueue
from games.tools import CreateUrl

from .importer import Importer
from .models import (
    URL,
    Game,
    GameAuthor,
    GameAuthorRole,
    GameTag,
    GameTagCategory,
    GameURL,
    GameURLCategory,
    Personality,
    PersonalityAlias,
    PersonalityAliasRedirect,
    PersonalityUrl,
    PersonalityURLCategory,
)
from .tasks.uploads import RecodeGame

PERM_ADD_GAME = "@auth"  # Also for file upload, game import, vote
logger = getLogger("web")

NON_CHAR_RE = re.compile(r"\W+")


def NormalizeName(x):
    return NON_CHAR_RE.sub(" ", x.lower()).strip()


FIRST_LAST_RE = re.compile(r"^(\w+) (\w+)$")


def GetOrCreateAlias(alias):
    if not alias.strip():
        return None
    try:
        x = PersonalityAliasRedirect.objects.get(name=alias)
        return x.hidden_for_id
    except PersonalityAliasRedirect.DoesNotExist:
        pass

    x = PersonalityAlias.objects.filter(name=alias)
    if x:
        return x[0].id

    return PersonalityAlias.objects.create(name=alias).id


def UpdateGameAuthors(request, game, authors, update):
    importer = Importer()
    existing_authors = {}  # (role_id, author_id) -> GameAuthor_id
    alias_to_urls = {}  # author_id -> [(type_slug, desc, url),]
    if update:
        for x in game.gameauthor_set.all():
            existing_authors[(x.role_id, x.author_id)] = x.id

    authors_to_add = []  # (role_id, author_id)
    for role, author, *rest in authors:
        if not isinstance(author, int):
            author = GetOrCreateAlias(author)
            if not author:
                continue
        if not isinstance(role, int):
            role = GameAuthorRole.objects.get_or_create(title=role)[0].id
        alias_to_urls.setdefault(author, [])
        if rest:
            alias_to_urls[author].append((
                PersonalityURLCategory.OtherSiteCatId(),
                rest[1],
                rest[0],
            ))
        t = (role, author)
        if t in existing_authors:
            del existing_authors[t]
        else:
            authors_to_add.append(t)

    if authors_to_add:
        objs = []
        for role, author in authors_to_add:
            obj = GameAuthor()
            obj.game = game
            obj.author_id = author
            obj.role_id = role
            objs.append(obj)
        GameAuthor.objects.bulk_create(objs)

    if existing_authors:
        GameAuthor.objects.filter(
            id__in=list(existing_authors.values())
        ).delete()

    for alias, urls in alias_to_urls.items():
        UpdatePersonalityUrls(importer, request, alias, urls, False)


def UpdateGameTags(request, game, tags, update):
    existing_tags = set()  # tag_id
    if update:
        for x in game.tags.select_related("category").all():
            if not request.perm(x.category.show_in_edit_perm):
                continue
            existing_tags.add(x.id)

    if tags:
        id_to_cat = {}
        name_to_cat = {}
        for x in GameTagCategory.objects.all():
            id_to_cat[x.id] = x
            name_to_cat[x.name] = x

        tags_to_add = []  # (tag_id)
        for x in tags:
            if not isinstance(x[0], int):
                x[0] = name_to_cat[x[0]]

            if not isinstance(x[1], int):
                cat = id_to_cat[x[0]]
                if cat.allow_new_tags:
                    x[1] = GameTag.objects.get_or_create(
                        name=x[1], category=cat
                    )[0].id
                else:
                    x[1] = GameTag.objects.get(name=x[1], category=cat)

            if x[1] in existing_tags:
                existing_tags.remove(x[1])
            else:
                tags_to_add.append(x[1])

        if tags_to_add:
            game.tags.add(*tags_to_add)

    if existing_tags:
        game.tags.remove(*list(game.tags.filter(id__in=existing_tags)))


def UpdatePersonalityUrls(importer, request, alias_id, data, update):
    alias = PersonalityAlias.objects.get(pk=alias_id)
    filtered_data = []
    if alias.personality:
        personality = alias.personality
        bio = personality.bio
        filtered_data = data
    else:
        personality = None
        bio = None
        for typ, desc, url in data:
            if typ != PersonalityURLCategory.OtherSiteCatId():
                continue
            x = importer.ImportAuthor(url)
            if "urls" in x:
                for y in x["urls"]:
                    if not y["urlcat_slug"]:
                        continue
                    filtered_data.append((
                        PersonalityURLCategory.objects.get(
                            symbolic_id=y["urlcat_slug"]
                        ).id,
                        y["description"],
                        y["url"],
                    ))
            if "bio" in x:
                bio = x["bio"]
            if "canonical" in x:
                y = PersonalityAlias.objects.filter(name=x["canonical"])[1:]
                if y and y.personality:
                    personality = y.personality
                    alias.personality = y.personality
                    bio = y.personality.bio
                    alias.save()
            if "canonical_url" in x:
                url = x["canonical_url"]
            filtered_data.append((typ, desc, url))
        if not personality:
            personality = Personality()
            personality.name = alias.name
            if bio:
                personality.bio = bio
            personality.save()
            alias.personality = personality
            alias.save()

    duplicates = set()
    data = []
    for x in filtered_data:
        v = (x[0], x[2])
        if v in duplicates:
            continue
        duplicates.add(v)
        data.append(x)

    existing_urls = {}  # (cat_id, url_text) -> (persurl, persurl_desc)
    for x in personality.personalityurl_set.select_related("url").all():
        existing_urls[(x.category_id, x.url.original_url)] = (
            x,
            x.description or "",
        )

    records_to_add = []  # (cat_id, persurl_desc, url_text)
    urls_to_add = []  # (url_text, cat_id)
    for x in data:
        t = (x[0], x[2])
        if t in existing_urls:
            if update:
                if x[1] != existing_urls[t][1]:
                    url = existing_urls[t][0]
                    url.description = x[1]
                    url.save()
                del existing_urls[t]
        else:
            records_to_add.append(tuple(x))
            urls_to_add.append((x[2], int(x[0])))

    if records_to_add:
        url_to_id = {}
        for u in URL.objects.filter(original_url__in=next(zip(*urls_to_add))):
            url_to_id[u.original_url] = u.id

        cats_to_check = set()
        for u, c in urls_to_add:
            if u not in url_to_id:
                cats_to_check.add(c)

        cat_to_cloneable = {}
        for c in PersonalityURLCategory.objects.filter(id__in=cats_to_check):
            cat_to_cloneable[c.id] = c.allow_cloning

        for u, c in urls_to_add:
            if u not in url_to_id:
                url = CreateUrl(
                    u, ok_to_clone=cat_to_cloneable[c], creator=request.user
                )
                url_to_id[u] = url.id

        objs = []
        for cat, desc, url in records_to_add:
            obj = PersonalityUrl()
            obj.category_id = cat
            obj.url_id = url_to_id[url]
            obj.personality = personality
            obj.description = desc or None
            objs.append(obj)
            if not bio and cat == PersonalityURLCategory.OtherSiteCatId():
                x = importer.ImportAuthor(url)
                if "bio" in x:
                    bio = x["bio"]
                    personality.bio = bio
                    personality.save()

        PersonalityUrl.objects.bulk_create(objs)

    if update and existing_urls:
        PersonalityUrl.objects.filter(
            id__in=[x[0].id for x in existing_urls.values()]
        ).delete()


def UpdateGameUrls(request, game, data, update, kill_existing=True):
    existing_urls = {}  # (cat_id, url_text) -> (gameurl, gameurl_desc)
    if update:
        for x in game.gameurl_set.select_related("url").all():
            existing_urls[(x.category_id, x.url.original_url)] = (
                x,
                x.description or "",
            )

    records_to_add = []  # (cat_id, gameurl_desc, url_text)
    urls_to_add = []  # (url_text, cat_id)
    to_skip = set()
    for x in data:
        t = (x[0], x[2])
        if t in to_skip:
            continue
        if t in existing_urls:
            if x[1] != existing_urls[t][1]:
                url = existing_urls[t][0]
                url.description = x[1]
                url.save()
            del existing_urls[t]
        else:
            records_to_add.append(tuple(x))
            urls_to_add.append((x[2], int(x[0])))
        to_skip.add(t)

    if records_to_add:
        url_to_id = {}
        for u in URL.objects.filter(original_url__in=next(zip(*urls_to_add))):
            url_to_id[u.original_url] = u.id

        cats_to_check = set()
        for u, c in urls_to_add:
            if u not in url_to_id:
                cats_to_check.add(c)

        cat_to_cloneable = {}
        for c in GameURLCategory.objects.filter(id__in=cats_to_check):
            cat_to_cloneable[c.id] = c.allow_cloning

        for u, c in urls_to_add:
            if u not in url_to_id:
                url = CreateUrl(
                    u, ok_to_clone=cat_to_cloneable[c], creator=request.user
                )
                url_to_id[u] = url.id

        objs = []
        for cat, desc, url in records_to_add:
            obj = GameURL()
            obj.category_id = cat
            obj.url_id = url_to_id[url]
            obj.game = game
            obj.description = desc or None
            if GameURLCategory.IsRecodable(cat):
                obj.save()
                Enqueue(RecodeGame, obj.id, name="RecodeGame(%d)" % obj.id)
            else:
                objs.append(obj)
        GameURL.objects.bulk_create(objs)

    if existing_urls and kill_existing:
        GameURL.objects.filter(
            id__in=[x[0].id for x in existing_urls.values()]
        ).delete()


def UpdateGame(request, j, update_edit_time=True, kill_existing_urls=True):
    if "game_id" in j:
        g = Game.objects.get(id=j["game_id"])
        request.perm.Ensure(g.edit_perm)
        if update_edit_time:
            g.edit_time = timezone.now()
    else:
        request.perm.Ensure(PERM_ADD_GAME)
        g = Game()
        g.creation_time = timezone.now()
        g.added_by = request.user

    g.title = j["title"]
    g.description = j.get("desc")
    g.release_date = (
        parse_date(j["release_date"]) if j.get("release_date") else None
    )

    g.save()
    UpdateGameUrls(
        request,
        g,
        j.get("links", []),
        "game_id" in j,
        kill_existing=kill_existing_urls,
    )
    UpdateGameTags(request, g, j.get("tags", []), "game_id" in j)
    UpdateGameAuthors(request, g, j.get("authors", []), "game_id" in j)

    return g.id


def Importer2Json(r):
    res = {}
    for x in ["title", "desc", "release_date"]:
        if x in r:
            res[x] = str(r[x])

    if "authors" in r:
        res["authors"] = []
        for x in r["authors"]:
            if "role_slug" in x:
                role = GameAuthorRole.objects.get(
                    symbolic_id=x["role_slug"]
                ).id
            else:
                role = r["role"]
            ls = [role, x["name"]]
            if "url" in x:
                ls.append(x["url"])
                ls.append(x["urldesc"])

            res["authors"].append(ls)

    if "tags" in r:
        res["tags"] = []
        for x in r["tags"]:
            if "tag_slug" in x:
                try:
                    tag = GameTag.objects.get(symbolic_id=x["tag_slug"])
                except:
                    logger.error("Cannot fetch tag %s" % x["tag_slug"])
                    raise
                cat = tag.category.id
                tag = tag.id
            else:
                tag = x["tag"]
                cat = GameTagCategory.objects.get(symbolic_id=x["cat_slug"]).id
            res["tags"].append([cat, tag])

    if "urls" in r:
        res["links"] = []
        for x in r["urls"]:
            cat = GameURLCategory.objects.get(symbolic_id=x["urlcat_slug"]).id
            desc = x.get("description")
            url = x["url"]
            res["links"].append([cat, desc, url])

    return res
