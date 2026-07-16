"""Offline tests: the committed realm file is reproducible and models the
full IdentityServer4 configuration (Config.cs inventory)."""
import json
import os

import generate_realm

HERE = os.path.dirname(os.path.abspath(__file__))
REALM_FILE = os.path.join(HERE, "..", "realm", "eshop-realm.json")

EXPECTED_AUDIENCES = {
    "orders", "basket", "marketing", "locations",
    "mobileshoppingagg", "webshoppingagg", "orders.signalrhub", "webhooks",
}
EXPECTED_CLIENTS = {
    "js", "xamarin", "mvc", "mvctest", "webhooksclient",
    "locationsswaggerui", "marketingswaggerui", "basketswaggerui",
    "orderingswaggerui", "mobileshoppingaggswaggerui",
    "webshoppingaggswaggerui", "webhooksswaggerui",
}


def load_realm():
    with open(REALM_FILE, encoding="utf-8") as f:
        return json.load(f)


def test_realm_file_is_reproducible():
    with open(REALM_FILE, encoding="utf-8") as f:
        committed = f.read()
    regenerated = json.dumps(generate_realm.build_realm(), indent=2, ensure_ascii=False) + "\n"
    assert committed == regenerated, "eshop-realm.json is stale; rerun realm/generate_realm.py"


def test_all_is4_api_resources_modeled_as_audience_scopes():
    realm = load_realm()
    scopes = {s["name"] for s in realm["clientScopes"]}
    assert EXPECTED_AUDIENCES <= scopes
    assert "catalog" in scopes  # future-use audience
    for scope in realm["clientScopes"]:
        if scope["name"] in EXPECTED_AUDIENCES | {"catalog"}:
            mappers = scope["protocolMappers"]
            assert any(
                m["protocolMapper"] == "oidc-audience-mapper"
                and m["config"]["included.custom.audience"] == scope["name"]
                for m in mappers
            )


def test_all_is4_clients_present():
    realm = load_realm()
    assert {c["clientId"] for c in realm["clients"]} == EXPECTED_CLIENTS


def clients_by_id():
    return {c["clientId"]: c for c in load_realm()["clients"]}


def test_js_client_modernized_to_code_pkce():
    js = clients_by_id()["js"]
    assert js["publicClient"] is True
    assert js["standardFlowEnabled"] is True
    assert js["implicitFlowEnabled"] is False
    assert js["attributes"]["pkce.code.challenge.method"] == "S256"
    assert js["redirectUris"] == ["${ESHOP_SPA_URL}/"]
    assert js["webOrigins"] == ["${ESHOP_SPA_URL}"]
    for scope in ["orders", "basket", "locations", "marketing",
                  "webshoppingagg", "orders.signalrhub", "webhooks", "profile"]:
        assert scope in js["defaultClientScopes"]


def test_catalog_audience_not_attached_to_any_client():
    for client in load_realm()["clients"]:
        assert "catalog" not in client["defaultClientScopes"]
        assert "catalog" not in client["optionalClientScopes"]


def test_offline_access_preserved():
    clients = clients_by_id()
    for client_id in ["xamarin", "mvc", "mvctest", "webhooksclient"]:
        assert "offline_access" in clients[client_id]["optionalClientScopes"], client_id
    assert "offline_access" not in clients["js"]["optionalClientScopes"]


def test_token_lifetimes():
    realm = load_realm()
    assert realm["accessTokenLifespan"] == 3600  # IS4 default
    clients = clients_by_id()
    for client_id in ["mvc", "mvctest", "webhooksclient"]:  # IS4: 2 hours
        assert clients[client_id]["attributes"]["access.token.lifespan"] == "7200", client_id


def test_swagger_clients_redirect_uris():
    clients = clients_by_id()
    for client_id in [c for c in EXPECTED_CLIENTS if c.endswith("swaggerui")]:
        client = clients[client_id]
        assert client["publicClient"] is True
        assert client["implicitFlowEnabled"] is True  # current Swagger UI flow
        assert len(client["redirectUris"]) == 1
        assert client["redirectUris"][0].endswith("/swagger/oauth2-redirect.html")
        assert client["attributes"]["post.logout.redirect.uris"].endswith("/swagger/")


def test_mvc_and_webhooks_redirect_uris():
    clients = clients_by_id()
    for client_id, env in [("mvc", "ESHOP_MVC_URL"), ("mvctest", "ESHOP_MVC_URL"),
                           ("webhooksclient", "ESHOP_WEBHOOKS_WEB_URL")]:
        client = clients[client_id]
        assert client["redirectUris"] == ["${" + env + "}/signin-oidc"]
        assert client["attributes"]["post.logout.redirect.uris"] == "${" + env + "}/signout-callback-oidc"


def test_no_secrets_committed():
    for client in load_realm()["clients"]:
        secret = client.get("secret")
        if secret is not None:
            assert secret.startswith("${") and secret.endswith("}"), \
                f"client {client['clientId']} has a literal secret committed"


def test_profile_claim_mappers_match_profileservice():
    realm = load_realm()
    eshop_profile = next(s for s in realm["clientScopes"] if s["name"] == "eshop-profile")
    claims = {m["config"]["claim.name"] for m in eshop_profile["protocolMappers"]}
    expected = {
        "unique_name", "preferred_username", "name", "last_name",
        "card_number", "card_holder", "card_security_number", "card_expiration",
        "address_city", "address_country", "address_state", "address_street",
        "address_zip_code",
    }
    assert claims == expected
