from django.core import signing


def BuildGameUserFingerprint(request, game):
    x = [game]
    if request.user.is_authenticated:
        x.append(request.user.id)
    return signing.dumps(x, salt='core.packages.game')
