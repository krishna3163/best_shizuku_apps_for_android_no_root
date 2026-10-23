import os
import re
import logging
from src import session

def _get_headers():
    headers = {}
    if "GITHUB_TOKEN" in os.environ:
        headers["Authorization"] = f"Bearer {os.environ['GITHUB_TOKEN']}"
    return headers

def get_latest_version(app_name: str, config: dict) -> str | None:
    repo = config.get("repo")
    tag = config.get("tag")
    if not repo or not tag:
        logging.error(f"Missing 'repo' or 'tag' in github config for {app_name}")
        return None
    
    url = f"https://api.github.com/repos/{repo}/releases/tags/{tag}"
    try:
        response = session.get(url, headers=_get_headers())
        if response.status_code == 200:
            data = response.json()
            versions = []
            for asset in data.get("assets", []):
                name = asset.get("name", "")
                # Extract version from something like com.instagram.android-426.0.0.37.68-arm64-v8a.apkm
                # Match digits and dots after hyphen
                m = re.search(r"-([\d\.]+)-", name)
                if m:
                    versions.append(m.group(1).strip("."))
                else:
                    # Fallback try generic version regex
                    m = re.search(r"([\d\.]+)", name)
                    if m:
                        versions.append(m.group(1).strip("."))
                        
            if versions:
                # Sort numerically
                versions.sort(key=lambda x: [int(p) for p in x.split('.') if p.isdigit()])
                logging.info(f"Latest version found on GitHub for {app_name}: {versions[-1]}")
                return versions[-1]
                
        elif response.status_code == 404:
            logging.debug(f"GitHub release not found for {url}")
        else:
            response.raise_for_status()
            
    except Exception as e:
        logging.error(f"Failed to fetch GitHub release for {app_name}: {e}")
    return None

def get_download_link(version: str, app_name: str, config: dict) -> str | None:
    repo = config.get("repo")
    tag = config.get("tag")
    if not repo or not tag:
        return None
        
    url = f"https://api.github.com/repos/{repo}/releases/tags/{tag}"
    try:
        response = session.get(url, headers=_get_headers())
        if response.status_code == 200:
            data = response.json()
            arch = config.get("arch", "arm64-v8a").lower()
            
            for asset in data.get("assets", []):
                name = asset.get("name", "").lower()
                # Check version and extension
                if version in name and name.endswith((".apk", ".apkm", ".xapk")):
                    # Check architecture match if arch is specified, allow all/both to passthrough
                    if arch in ("all", "both") or arch in name:
                        logging.info(f"Found GitHub download link for {app_name} {version}")
                        return asset.get("browser_download_url")
                        
            # If explicit arch failed, try to fallback to first matched version available
            for asset in data.get("assets", []):
                name = asset.get("name", "").lower()
                if version in name and name.endswith((".apk", ".apkm", ".xapk")):
                    logging.info(f"Fallback arch: Found GitHub download link for {app_name} {version}")
                    return asset.get("browser_download_url")
                    
    except Exception as e:
        logging.error(f"Failed to get GitHub download link for {app_name}: {e}")
        
    return None
