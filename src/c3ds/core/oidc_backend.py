from social_core.backends.open_id_connect import OpenIdConnectAuth


class C3dsOIDCAuth(OpenIdConnectAuth):
    DEFAULT_SCOPE = ["openid", "profile", "email", "groups"]
