"""Small authenticated REST client for workspace setup and deployment verification."""

from __future__ import annotations

import time
from urllib.parse import urlparse
from uuid import UUID

import requests
from azure.identity import AzureCliCredential

FABRIC_ROOT = "https://api.fabric.microsoft.com/v1"
POWERBI_ROOT = "https://api.powerbi.com/v1.0/myorg"


class FabricClient:
    def __init__(self, credential=None, session=None):
        self.credential = credential or AzureCliCredential()
        self.session = session or requests.Session()

    def request(self, method: str, url: str, *, payload=None) -> requests.Response:
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.netloc not in (
            "api.fabric.microsoft.com", "api.powerbi.com"
        ):
            raise ValueError(f"Unexpected API URL: {url}")
        is_fabric = parsed.netloc == "api.fabric.microsoft.com"
        scope = (
            "https://api.fabric.microsoft.com/.default"
            if is_fabric else "https://analysis.windows.net/powerbi/api/.default"
        )
        headers = {"Authorization": f"Bearer {self.credential.get_token(scope).token}"}
        if is_fabric:
            headers["x-ms-fabric-skill"] = "semantic-model-authoring"
        response = self.session.request(
            method, url, headers=headers, json=payload, timeout=60, allow_redirects=False
        )
        response.raise_for_status()
        if 300 <= response.status_code < 400:
            raise RuntimeError(f"Unexpected redirect from {url}.")
        return response

    def list_all(self, url: str) -> list[dict]:
        origin = urlparse(url).netloc
        visited = set()
        values = []
        while url:
            if url in visited or urlparse(url).netloc != origin:
                raise ValueError("Invalid or cyclic API pagination URL.")
            visited.add(url)
            body = self.request("GET", url).json()
            values.extend(body["value"])
            url = body.get("continuationUri") or body.get("@odata.nextLink") or body.get("nextLink")
        return values

    def create_workspace(self, name: str, capacity_id: str) -> dict:
        response = self.request(
            "POST", f"{FABRIC_ROOT}/workspaces",
            payload={"displayName": name, "capacityId": capacity_id},
        )
        if response.status_code != 201:
            raise RuntimeError(f"Workspace creation returned unexpected status {response.status_code}.")
        return response.json()

    def refresh_model(self, workspace_id: str, model_id: str, *, timeout: int = 1800) -> None:
        url = f"{POWERBI_ROOT}/groups/{workspace_id}/datasets/{model_id}/refreshes"
        response = self.request(
            "POST", url, payload={"type": "full", "commitMode": "transactional", "retryCount": 0}
        )
        if response.status_code != 202:
            raise RuntimeError("Enhanced refresh did not return HTTP 202.")
        request_id = response.headers.get("x-ms-request-id")
        if not request_id:
            location = response.headers.get("Location")
            if not location:
                raise RuntimeError("Enhanced refresh returned neither a request ID nor a Location header.")
            request_id = urlparse(location).path.rstrip("/").rsplit("/", 1)[-1]
        self.wait_for_refresh(workspace_id, model_id, request_id, timeout=timeout)

    def wait_for_refresh(
        self, workspace_id: str, model_id: str, request_id: str, *, timeout: int = 1800
    ) -> None:
        try:
            refresh_id = UUID(request_id)
        except (ValueError, TypeError, AttributeError) as error:
            raise ValueError("Enhanced refresh returned an invalid request ID.") from error
        if refresh_id.int == 0:
            raise ValueError("Enhanced refresh returned the zero request ID.")
        # Location can use a regional URL; poll the documented API with the operation ID.
        location = (
            f"{POWERBI_ROOT}/groups/{workspace_id}/datasets/{model_id}/refreshes/{refresh_id}"
        )
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            result = self.request("GET", location)
            body = result.json()
            status = body.get("status")
            if status == "Completed":
                print(f"Refresh completed: {model_id}")
                return
            if status in ("Failed", "Cancelled", "Disabled"):
                raise RuntimeError(
                    f"Model refresh {status}: {model_id}. "
                    "Check refresh history and data source credentials in Power BI Service."
                )
            if status not in ("Unknown", "NotStarted", "InProgress"):
                raise RuntimeError(f"Unexpected refresh status: {status!r}.")
            time.sleep(min(10, max(0, deadline - time.monotonic())))
        raise TimeoutError(f"Model refresh exceeded {timeout} seconds: {model_id}.")
