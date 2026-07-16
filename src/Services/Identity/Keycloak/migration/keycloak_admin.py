"""Minimal Keycloak Admin REST API client used by the migration scripts."""
import os

import requests


class KeycloakAdmin:
    def __init__(self, base_url=None, realm=None, username=None, password=None):
        self.base_url = (base_url or os.environ.get("KEYCLOAK_URL", "http://localhost:5106")).rstrip("/")
        self.realm = realm or os.environ.get("KEYCLOAK_REALM", "eshop")
        self._username = username or os.environ.get("KEYCLOAK_ADMIN_USERNAME", "admin")
        self._password = password or os.environ["KEYCLOAK_ADMIN_PASSWORD"]
        self._session = requests.Session()
        self._token = None

    def _login(self):
        resp = requests.post(
            f"{self.base_url}/realms/master/protocol/openid-connect/token",
            data={
                "grant_type": "password",
                "client_id": "admin-cli",
                "username": self._username,
                "password": self._password,
            },
            timeout=30,
        )
        resp.raise_for_status()
        self._token = resp.json()["access_token"]
        self._session.headers["Authorization"] = f"Bearer {self._token}"

    def _request(self, method, path, **kwargs):
        if self._token is None:
            self._login()
        url = f"{self.base_url}/admin/realms/{self.realm}{path}"
        resp = self._session.request(method, url, timeout=30, **kwargs)
        if resp.status_code == 401:
            self._login()
            resp = self._session.request(method, url, timeout=30, **kwargs)
        return resp

    def get_realm(self):
        resp = self._request("GET", "")
        resp.raise_for_status()
        return resp.json()

    def get_clients(self):
        resp = self._request("GET", "/clients", params={"max": 200})
        resp.raise_for_status()
        return resp.json()

    def get_client_scopes(self):
        resp = self._request("GET", "/client-scopes")
        resp.raise_for_status()
        return resp.json()

    def find_user(self, username):
        resp = self._request("GET", "/users", params={"username": username, "exact": "true"})
        resp.raise_for_status()
        users = resp.json()
        return users[0] if users else None

    def create_user(self, representation):
        resp = self._request("POST", "/users", json=representation)
        resp.raise_for_status()
        return resp.headers.get("Location", "").rsplit("/", 1)[-1]

    def partial_import_users(self, representations, if_resource_exists="SKIP"):
        """Import users via realm partialImport, which preserves supplied ids
        (POST /users ignores the ``id`` field)."""
        resp = self._request(
            "POST",
            "/partialImport",
            json={"ifResourceExists": if_resource_exists, "users": representations},
        )
        resp.raise_for_status()
        return resp.json()

    def update_user(self, user_id, representation):
        resp = self._request("PUT", f"/users/{user_id}", json=representation)
        resp.raise_for_status()

    def delete_user(self, user_id):
        resp = self._request("DELETE", f"/users/{user_id}")
        resp.raise_for_status()

    def list_users(self, first=0, max_results=100, query=None):
        params = {"first": first, "max": max_results}
        if query:
            params["q"] = query
        resp = self._request("GET", "/users", params=params)
        resp.raise_for_status()
        return resp.json()

    def count_users(self, query=None):
        params = {"q": query} if query else None
        resp = self._request("GET", "/users/count", params=params)
        resp.raise_for_status()
        return int(resp.text)
