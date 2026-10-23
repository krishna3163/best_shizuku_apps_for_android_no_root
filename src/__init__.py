import os
import logging

try:
    from curl_cffi import requests
    from curl_cffi.requests.impersonate import DEFAULT_CHROME
    session = requests.Session(impersonate=DEFAULT_CHROME)
except ImportError:
    import requests
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36"
    })

# Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# Env Vars
github_token = os.getenv('GITHUB_TOKEN') or os.getenv('GH_TOKEN')
repository = os.getenv('GITHUB_REPOSITORY')
endpoint_url = os.getenv('ENDPOINT_URL')
access_key_id = os.getenv('AWS_ACCESS_KEY_ID')
secret_access_key = os.getenv('AWS_SECRET_ACCESS_KEY')
bucket_name = os.getenv('BUCKET_NAME')

# APKmirror base url
base_url = "https://www.apkmirror.com"

gh = None
try:
    from github import Github
    if github_token:
        logging.info("GitHub token detected; using authenticated GitHub API client")
        gh = Github(github_token)
    else:
        if os.getenv("CI"):
            logging.warning("No GITHUB_TOKEN/GH_TOKEN detected in CI; GitHub release lookups may fail")
        gh = Github()
except Exception as e:
    logging.debug("PyGithub not available or initialization failed: %s", e)
