"""GitHub REST API client with authentication, rate-limit awareness, and retries."""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Optional

import requests

logger = logging.getLogger("apk-sync")

# Retryable HTTP status codes
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
MAX_RETRIES = 3
BASE_DELAY = 2  # seconds


class GitHubAPI:
    """Thin wrapper around the GitHub REST API v3."""

    BASE_URL = "https://api.github.com"

    def __init__(self, token: Optional[str] = None) -> None:
        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/vnd.github+json",
            "User-Agent": "shizuku-apk-sync/1.0",
            "X-GitHub-Api-Version": "2022-11-28",
        })
        token = token or os.environ.get("GITHUB_TOKEN", "")
        if token:
            self.session.headers["Authorization"] = f"Bearer {token}"
        self._remaining: Optional[int] = None
        self._reset: Optional[float] = None

    # ------------------------------------------------------------------
    # Rate-limit helpers
    # ------------------------------------------------------------------

    def _update_rate_limit(self, response: requests.Response) -> None:
        """Track rate-limit headers from every response."""
        remaining = response.headers.get("X-RateLimit-Remaining")
        reset = response.headers.get("X-RateLimit-Reset")
        if remaining is not None:
            self._remaining = int(remaining)
        if reset is not None:
            self._reset = float(reset)

    def _wait_for_rate_limit(self) -> None:
        """Sleep if we're close to hitting the rate limit."""
        if self._remaining is not None and self._remaining < 5 and self._reset:
            wait = max(0, self._reset - time.time()) + 1
            logger.warning("Rate limit nearly exhausted (%d remaining). Sleeping %.0fs.", self._remaining, wait)
            time.sleep(wait)

    # ------------------------------------------------------------------
    # Core HTTP with retries
    # ------------------------------------------------------------------

    def _request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        """Perform an HTTP request with exponential-backoff retries."""
        self._wait_for_rate_limit()

        last_exc: Optional[Exception] = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = self.session.request(method, url, timeout=30, **kwargs)
                self._update_rate_limit(response)

                if response.status_code in RETRYABLE_STATUS_CODES:
                    delay = BASE_DELAY ** attempt
                    if response.status_code == 429:
                        retry_after = response.headers.get("Retry-After")
                        if retry_after:
                            delay = max(delay, int(retry_after))
                    logger.warning(
                        "HTTP %d from %s (attempt %d/%d). Retrying in %ds...",
                        response.status_code, url, attempt, MAX_RETRIES, delay,
                    )
                    time.sleep(delay)
                    continue

                return response

            except (requests.ConnectionError, requests.Timeout) as exc:
                last_exc = exc
                delay = BASE_DELAY ** attempt
                logger.warning(
                    "Network error on %s (attempt %d/%d): %s. Retrying in %ds...",
                    url, attempt, MAX_RETRIES, exc, delay,
                )
                time.sleep(delay)

        # Final attempt failed
        if last_exc:
            raise last_exc
        # Return last response even if it had a retryable status
        return response  # type: ignore[possibly-undefined]

    def get(self, endpoint: str, **kwargs: Any) -> requests.Response:
        """GET request against the GitHub API."""
        url = endpoint if endpoint.startswith("http") else f"{self.BASE_URL}{endpoint}"
        return self._request("GET", url, **kwargs)

    # ------------------------------------------------------------------
    # Release endpoints
    # ------------------------------------------------------------------

    def get_latest_release(self, repo: str) -> Optional[dict[str, Any]]:
        """GET /repos/{owner}/{repo}/releases/latest — returns None on 404."""
        resp = self.get(f"/repos/{repo}/releases/latest")
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()

    def get_releases(self, repo: str, per_page: int = 30) -> list[dict[str, Any]]:
        """GET /repos/{owner}/{repo}/releases — returns a list of releases."""
        resp = self.get(f"/repos/{repo}/releases", params={"per_page": per_page})
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
        return resp.json()

    def get_release_by_tag(self, repo: str, tag: str) -> Optional[dict[str, Any]]:
        """GET /repos/{owner}/{repo}/releases/tags/{tag}"""
        resp = self.get(f"/repos/{repo}/releases/tags/{tag}")
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------
    # Asset download
    # ------------------------------------------------------------------

    def download_asset(self, url: str, dest_path: str) -> str:
        """Download a release asset to *dest_path* and return the path.

        Uses the ``Accept: application/octet-stream`` header so GitHub
        redirects to the binary blob.
        """
        self._wait_for_rate_limit()
        headers = dict(self.session.headers)
        headers["Accept"] = "application/octet-stream"

        last_exc: Optional[Exception] = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                with self.session.get(url, headers=headers, stream=True, timeout=120, allow_redirects=True) as resp:
                    self._update_rate_limit(resp)
                    if resp.status_code in RETRYABLE_STATUS_CODES:
                        delay = BASE_DELAY ** attempt
                        logger.warning("Download HTTP %d (attempt %d/%d)", resp.status_code, attempt, MAX_RETRIES)
                        time.sleep(delay)
                        continue
                    resp.raise_for_status()
                    with open(dest_path, "wb") as fh:
                        for chunk in resp.iter_content(chunk_size=8192):
                            fh.write(chunk)
                return dest_path
            except (requests.ConnectionError, requests.Timeout) as exc:
                last_exc = exc
                delay = BASE_DELAY ** attempt
                logger.warning("Download error (attempt %d/%d): %s", attempt, MAX_RETRIES, exc)
                time.sleep(delay)

        if last_exc:
            raise last_exc
        raise RuntimeError(f"Failed to download {url}")

    # ------------------------------------------------------------------
    # Release management (for our mirror repo)
    # ------------------------------------------------------------------

    def get_repo_release_by_tag(self, repo: str, tag: str) -> Optional[dict[str, Any]]:
        """Check if a release with *tag* already exists in *repo*."""
        return self.get_release_by_tag(repo, tag)

    def create_release(
        self,
        repo: str,
        tag: str,
        name: str,
        body: str,
        draft: bool = False,
        prerelease: bool = False,
    ) -> dict[str, Any]:
        """Create a new release in *repo*."""
        url = f"{self.BASE_URL}/repos/{repo}/releases"
        payload = {
            "tag_name": tag,
            "name": name,
            "body": body,
            "draft": draft,
            "prerelease": prerelease,
        }
        resp = self._request("POST", url, json=payload)
        resp.raise_for_status()
        return resp.json()

    def upload_release_asset(
        self,
        upload_url: str,
        filepath: str,
        content_type: str = "application/vnd.android.package-archive",
    ) -> dict[str, Any]:
        """Upload an asset to an existing release.

        *upload_url* is the ``upload_url`` field from the release object
        (it contains ``{?name,label}`` which we strip).
        """
        upload_url = upload_url.split("{")[0]
        filename = os.path.basename(filepath)
        with open(filepath, "rb") as fh:
            resp = self._request(
                "POST",
                upload_url,
                params={"name": filename},
                headers={"Content-Type": content_type},
                data=fh,
            )
        resp.raise_for_status()
        return resp.json()

    def get_release_assets(self, repo: str, release_id: int) -> list[dict[str, Any]]:
        """List assets attached to a release."""
        resp = self.get(f"/repos/{repo}/releases/{release_id}/assets")
        resp.raise_for_status()
        return resp.json()

    def get_repo_info(self, repo: str) -> Optional[dict[str, Any]]:
        """GET /repos/{owner}/{repo} — basic repository metadata."""
        resp = self.get(f"/repos/{repo}")
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()
