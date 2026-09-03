from social_core.exceptions import AuthForbidden


class GroupNotAllowed(AuthForbidden):
    """Raised when the authenticated account has no permitted group."""

    def __str__(self):
        return "Your account is not a member of any group permitted to sign in."


def require_oidc_group(backend, details, response, *args, **kwargs):
    allow_groups = set(backend.setting("ALLOW_GROUPS", []))
    if not allow_groups:
        return

    groups_claim = backend.setting("GROUPS_CLAIM", "groups")

    # Check userinfo (response) first, then id_token
    userinfo = response if isinstance(response, dict) else {}
    id_token = getattr(backend, "id_token", {}) or {}

    groups = set(userinfo.get(groups_claim, []) or id_token.get(groups_claim, []))

    if not groups.intersection(allow_groups):
        raise GroupNotAllowed(backend)


def make_superuser(response, user, backend, *args, **kwargs):
    user.is_superuser = True
    user.is_staff = True
    user.save()
