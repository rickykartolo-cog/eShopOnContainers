#!/usr/bin/env python3
"""Generates eshop-realm.json deterministically.

The realm models the IdentityServer4 configuration from
src/Services/Identity/Identity.API/Configuration/Config.cs on the
.NET Core 3.1 baseline. Regenerating this file must be byte-identical
to the committed eshop-realm.json (enforced by tests).

URL and secret values are `${ENV_VAR}` placeholders resolved by
Keycloak's built-in realm-import placeholder replacement; defaults are
supplied at the docker-compose layer (see src/docker-compose.keycloak.yml).
"""
import json
import os

# IdentityServer4 ApiResources -> audiences (Config.GetApis()).
API_AUDIENCES = [
    "orders",
    "basket",
    "marketing",
    "locations",
    "mobileshoppingagg",
    "webshoppingagg",
    "orders.signalrhub",
    "webhooks",
    # Future-use audience only. It is NOT attached to any client, so no
    # currently-anonymous Catalog route gains authentication.
    "catalog",
]

# Custom user claims issued by ProfileService.GetClaimsFromUser.
PROFILE_ATTRIBUTE_CLAIMS = [
    "name",
    "last_name",
    "card_number",
    "card_holder",
    "card_security_number",
    "card_expiration",
    "address_city",
    "address_country",
    "address_state",
    "address_street",
    "address_zip_code",
]

TWO_HOURS = "7200"  # AccessTokenLifetime/IdentityTokenLifetime of mvc, mvctest, webhooksclient


def audience_scope(name):
    return {
        "name": name,
        "description": f"eShop API audience scope: {name}",
        "protocol": "openid-connect",
        "attributes": {
            "include.in.token.scope": "true",
            "display.on.consent.screen": "false",
        },
        "protocolMappers": [
            {
                "name": f"{name}-audience",
                "protocol": "openid-connect",
                "protocolMapper": "oidc-audience-mapper",
                "consentRequired": False,
                "config": {
                    "included.custom.audience": name,
                    "id.token.claim": "false",
                    "access.token.claim": "true",
                },
            }
        ],
    }


def builtin_scopes():
    """Keycloak built-in scopes referenced by the clients.

    A realm file that defines ``clientScopes`` must include the built-in
    scopes explicitly; the importer does not create them.
    """
    return [
        {
            "name": "basic",
            "description": "OpenID Connect scope for add all basic claims to the token",
            "protocol": "openid-connect",
            "attributes": {
                "include.in.token.scope": "false",
                "display.on.consent.screen": "false",
            },
            "protocolMappers": [
                {
                    "name": "auth_time",
                    "protocol": "openid-connect",
                    "protocolMapper": "oidc-usersessionmodel-note-mapper",
                    "consentRequired": False,
                    "config": {
                        "user.session.note": "AUTH_TIME",
                        "claim.name": "auth_time",
                        "jsonType.label": "long",
                        "id.token.claim": "true",
                        "access.token.claim": "true",
                    },
                },
                {
                    "name": "sub",
                    "protocol": "openid-connect",
                    "protocolMapper": "oidc-sub-mapper",
                    "consentRequired": False,
                    "config": {"access.token.claim": "true"},
                },
            ],
        },
        {
            "name": "profile",
            "description": "OpenID Connect built-in scope: profile",
            "protocol": "openid-connect",
            "attributes": {
                "include.in.token.scope": "true",
                "display.on.consent.screen": "false",
            },
            # NOTE: no oidc-full-name-mapper here: the `name` claim must be
            # the user's Name attribute alone (ProfileService parity), issued
            # by the eshop-profile scope.
            "protocolMappers": [
                {
                    "name": "given name",
                    "protocol": "openid-connect",
                    "protocolMapper": "oidc-usermodel-attribute-mapper",
                    "consentRequired": False,
                    "config": {
                        "user.attribute": "firstName",
                        "claim.name": "given_name",
                        "jsonType.label": "String",
                        "id.token.claim": "true",
                        "access.token.claim": "true",
                        "userinfo.token.claim": "true",
                    },
                },
                {
                    "name": "family name",
                    "protocol": "openid-connect",
                    "protocolMapper": "oidc-usermodel-attribute-mapper",
                    "consentRequired": False,
                    "config": {
                        "user.attribute": "lastName",
                        "claim.name": "family_name",
                        "jsonType.label": "String",
                        "id.token.claim": "true",
                        "access.token.claim": "true",
                        "userinfo.token.claim": "true",
                    },
                },
            ],
        },
        {
            "name": "email",
            "description": "OpenID Connect built-in scope: email",
            "protocol": "openid-connect",
            "attributes": {
                "include.in.token.scope": "true",
                "display.on.consent.screen": "false",
            },
            "protocolMappers": [
                {
                    "name": "email",
                    "protocol": "openid-connect",
                    "protocolMapper": "oidc-usermodel-attribute-mapper",
                    "consentRequired": False,
                    "config": {
                        "user.attribute": "email",
                        "claim.name": "email",
                        "jsonType.label": "String",
                        "id.token.claim": "true",
                        "access.token.claim": "true",
                        "userinfo.token.claim": "true",
                    },
                },
                {
                    "name": "email verified",
                    "protocol": "openid-connect",
                    "protocolMapper": "oidc-usermodel-property-mapper",
                    "consentRequired": False,
                    "config": {
                        "user.attribute": "emailVerified",
                        "claim.name": "email_verified",
                        "jsonType.label": "boolean",
                        "id.token.claim": "true",
                        "access.token.claim": "true",
                        "userinfo.token.claim": "true",
                    },
                },
            ],
        },
        {
            "name": "offline_access",
            "description": "OpenID Connect built-in scope: offline_access",
            "protocol": "openid-connect",
            "attributes": {
                "consent.screen.text": "${offlineAccessScopeConsentText}",
                "display.on.consent.screen": "true",
            },
        },
    ]


def eshop_profile_scope():
    mappers = [
        {
            "name": "eshop-unique-name",
            "protocol": "openid-connect",
            "protocolMapper": "oidc-usermodel-property-mapper",
            "consentRequired": False,
            "config": {
                "user.attribute": "username",
                "claim.name": "unique_name",
                "jsonType.label": "String",
                "id.token.claim": "true",
                "access.token.claim": "true",
                "userinfo.token.claim": "true",
            },
        },
        {
            "name": "eshop-preferred-username",
            "protocol": "openid-connect",
            "protocolMapper": "oidc-usermodel-property-mapper",
            "consentRequired": False,
            "config": {
                "user.attribute": "username",
                "claim.name": "preferred_username",
                "jsonType.label": "String",
                "id.token.claim": "true",
                "access.token.claim": "true",
                "userinfo.token.claim": "true",
            },
        },
    ]
    for claim in PROFILE_ATTRIBUTE_CLAIMS:
        mappers.append(
            {
                "name": f"eshop-{claim}",
                "protocol": "openid-connect",
                "protocolMapper": "oidc-usermodel-attribute-mapper",
                "consentRequired": False,
                "config": {
                    "user.attribute": claim,
                    "claim.name": claim,
                    "jsonType.label": "String",
                    "id.token.claim": "true",
                    "access.token.claim": "true",
                    "userinfo.token.claim": "true",
                    "aggregate.attrs": "false",
                    "multivalued": "false",
                },
            }
        )
    return {
        "name": "eshop-profile",
        "description": "eShop custom user profile claims (ProfileService parity)",
        "protocol": "openid-connect",
        "attributes": {
            "include.in.token.scope": "false",
            "display.on.consent.screen": "false",
        },
        "protocolMappers": mappers,
    }


def client(
    client_id,
    name,
    *,
    public=False,
    secret_env=None,
    standard_flow=True,
    implicit_flow=False,
    direct_access=False,
    pkce=False,
    redirect_uris=(),
    post_logout_redirect_uris=(),
    web_origins=(),
    default_scopes=(),
    optional_scopes=(),
    access_token_lifespan=None,
):
    attributes = {
        "post.logout.redirect.uris": "##".join(post_logout_redirect_uris),
        "oauth2.device.authorization.grant.enabled": "false",
        "oidc.ciba.grant.enabled": "false",
    }
    if pkce:
        attributes["pkce.code.challenge.method"] = "S256"
    if access_token_lifespan is not None:
        attributes["access.token.lifespan"] = access_token_lifespan
    c = {
        "clientId": client_id,
        "name": name,
        "enabled": True,
        "protocol": "openid-connect",
        "publicClient": public,
        "bearerOnly": False,
        "consentRequired": False,  # RequireConsent = false on every IS4 client
        "standardFlowEnabled": standard_flow,
        "implicitFlowEnabled": implicit_flow,
        "directAccessGrantsEnabled": direct_access,
        "serviceAccountsEnabled": False,
        "frontchannelLogout": False,
        "fullScopeAllowed": False,
        "redirectUris": list(redirect_uris),
        "webOrigins": list(web_origins),
        "attributes": attributes,
        "defaultClientScopes": ["basic"] + list(default_scopes),
        "optionalClientScopes": list(optional_scopes),
    }
    if not public and secret_env:
        c["secret"] = "${" + secret_env + "}"
    return c


def build_clients():
    user_scopes = ["profile", "email", "eshop-profile"]
    clients = [
        # SPA client. IS4 used implicit flow; modernized to Authorization
        # Code + PKCE (the one permitted protocol modernization).
        client(
            "js",
            "eShop SPA OpenId Client",
            public=True,
            standard_flow=True,
            pkce=True,
            redirect_uris=["${ESHOP_SPA_URL}/"],
            post_logout_redirect_uris=["${ESHOP_SPA_URL}/"],
            web_origins=["${ESHOP_SPA_URL}"],
            default_scopes=user_scopes
            + [
                "orders",
                "basket",
                "locations",
                "marketing",
                "webshoppingagg",
                "orders.signalrhub",
                "webhooks",
            ],
        ),
        # IS4: Hybrid + PKCE + offline access -> Authorization Code + PKCE.
        client(
            "xamarin",
            "eShop Xamarin OpenId Client",
            secret_env="ESHOP_KEYCLOAK_XAMARIN_CLIENT_SECRET",
            pkce=True,
            redirect_uris=["${ESHOP_XAMARIN_CALLBACK}"],
            post_logout_redirect_uris=["${ESHOP_XAMARIN_CALLBACK}/Account/Redirecting"],
            default_scopes=user_scopes
            + [
                "orders",
                "basket",
                "locations",
                "marketing",
                "mobileshoppingagg",
                "webhooks",
            ],
            optional_scopes=["offline_access"],
        ),
        # IS4: Hybrid + offline access -> Authorization Code.
        client(
            "mvc",
            "MVC Client",
            secret_env="ESHOP_KEYCLOAK_MVC_CLIENT_SECRET",
            redirect_uris=["${ESHOP_MVC_URL}/signin-oidc"],
            post_logout_redirect_uris=["${ESHOP_MVC_URL}/signout-callback-oidc"],
            default_scopes=user_scopes
            + [
                "orders",
                "basket",
                "locations",
                "marketing",
                "webshoppingagg",
                "orders.signalrhub",
                "webhooks",
            ],
            optional_scopes=["offline_access"],
            access_token_lifespan=TWO_HOURS,
        ),
        client(
            "webhooksclient",
            "Webhooks Client",
            secret_env="ESHOP_KEYCLOAK_WEBHOOKSCLIENT_CLIENT_SECRET",
            redirect_uris=["${ESHOP_WEBHOOKS_WEB_URL}/signin-oidc"],
            post_logout_redirect_uris=["${ESHOP_WEBHOOKS_WEB_URL}/signout-callback-oidc"],
            default_scopes=user_scopes + ["webhooks"],
            optional_scopes=["offline_access"],
            access_token_lifespan=TWO_HOURS,
        ),
        # Test client; direct access grants enabled to support automated
        # token-issuance tests (Resource Owner Password), test use only.
        client(
            "mvctest",
            "MVC Client Test",
            secret_env="ESHOP_KEYCLOAK_MVCTEST_CLIENT_SECRET",
            direct_access=True,
            redirect_uris=["${ESHOP_MVC_URL}/signin-oidc"],
            post_logout_redirect_uris=["${ESHOP_MVC_URL}/signout-callback-oidc"],
            default_scopes=user_scopes
            + [
                "orders",
                "basket",
                "locations",
                "marketing",
                "webshoppingagg",
                "webhooks",
            ],
            optional_scopes=["offline_access"],
            access_token_lifespan=TWO_HOURS,
        ),
    ]

    swagger_clients = [
        ("locationsswaggerui", "Locations Swagger UI", "ESHOP_LOCATIONS_API_URL", ["locations"]),
        ("marketingswaggerui", "Marketing Swagger UI", "ESHOP_MARKETING_API_URL", ["marketing"]),
        ("basketswaggerui", "Basket Swagger UI", "ESHOP_BASKET_API_URL", ["basket"]),
        ("orderingswaggerui", "Ordering Swagger UI", "ESHOP_ORDERING_API_URL", ["orders"]),
        (
            "mobileshoppingaggswaggerui",
            "Mobile Shopping Aggregattor Swagger UI",
            "ESHOP_MOBILESHOPPINGAGG_URL",
            ["mobileshoppingagg"],
        ),
        (
            "webshoppingaggswaggerui",
            "Web Shopping Aggregattor Swagger UI",
            "ESHOP_WEBSHOPPINGAGG_URL",
            ["webshoppingagg", "basket"],
        ),
        ("webhooksswaggerui", "WebHooks Service Swagger UI", "ESHOP_WEBHOOKS_API_URL", ["webhooks"]),
    ]
    for client_id, name, url_env, scopes in swagger_clients:
        # IS4 used implicit flow for Swagger UI. Both implicit (current
        # Swagger UI behavior) and Authorization Code + PKCE are enabled so
        # the Swagger clients keep working before and after their cutover.
        clients.append(
            client(
                client_id,
                name,
                public=True,
                standard_flow=True,
                implicit_flow=True,
                pkce=True,
                redirect_uris=["${" + url_env + "}/swagger/oauth2-redirect.html"],
                post_logout_redirect_uris=["${" + url_env + "}/swagger/"],
                web_origins=["${" + url_env + "}"],
                default_scopes=scopes,
            )
        )
    return clients


def build_realm():
    return {
        "realm": "eshop",
        "displayName": "eShopOnContainers",
        "enabled": True,
        "sslRequired": "external",
        "registrationAllowed": False,
        "loginWithEmailAllowed": True,
        "duplicateEmailsAllowed": False,
        "resetPasswordAllowed": True,
        "bruteForceProtected": True,
        # IdentityServer4 default access token lifetime (js/xamarin/swagger
        # clients): 1 hour. mvc/mvctest/webhooksclient override to 2h via
        # per-client access.token.lifespan attributes.
        "accessTokenLifespan": 3600,
        "accessTokenLifespanForImplicitFlow": 3600,
        "ssoSessionIdleTimeout": 7200,
        "ssoSessionMaxLifespan": 36000,
        # Identity.API AppSettings PermanentTokenLifetimeDays = 365.
        "offlineSessionIdleTimeout": 2592000,
        "offlineSessionMaxLifespanEnabled": True,
        "offlineSessionMaxLifespan": 31536000,
        # Allow unmanaged user attributes so migrated ProfileService claims
        # (card_*, address_*, ...) can be stored without a managed profile
        # schema (Keycloak 24+ drops unmanaged attributes by default).
        "components": {
            "org.keycloak.userprofile.UserProfileProvider": [
                {
                    "providerId": "declarative-user-profile",
                    "subComponents": {},
                    "config": {
                        "kc.user.profile.config": [
                            json.dumps(
                                {
                                    "attributes": [
                                        {
                                            "name": "username",
                                            "displayName": "${username}",
                                            "validations": {
                                                "length": {"min": 3, "max": 255},
                                                "username-prohibited-characters": {},
                                                "up-username-not-idn-homograph": {},
                                            },
                                            "permissions": {"view": ["admin", "user"], "edit": ["admin", "user"]},
                                            "multivalued": False,
                                        },
                                        {
                                            "name": "email",
                                            "displayName": "${email}",
                                            "validations": {"email": {}, "length": {"max": 255}},
                                            "permissions": {"view": ["admin", "user"], "edit": ["admin", "user"]},
                                            "multivalued": False,
                                        },
                                        {
                                            "name": "firstName",
                                            "displayName": "${firstName}",
                                            "validations": {"length": {"max": 255}, "person-name-prohibited-characters": {}},
                                            "permissions": {"view": ["admin", "user"], "edit": ["admin", "user"]},
                                            "multivalued": False,
                                        },
                                        {
                                            "name": "lastName",
                                            "displayName": "${lastName}",
                                            "validations": {"length": {"max": 255}, "person-name-prohibited-characters": {}},
                                            "permissions": {"view": ["admin", "user"], "edit": ["admin", "user"]},
                                            "multivalued": False,
                                        },
                                    ],
                                    "groups": [],
                                    "unmanagedAttributePolicy": "ENABLED",
                                }
                            )
                        ]
                    },
                }
            ]
        },
        "clientScopes": builtin_scopes()
        + [eshop_profile_scope()]
        + [audience_scope(a) for a in API_AUDIENCES],
        "clients": build_clients(),
    }


def main():
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "eshop-realm.json")
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(build_realm(), f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
