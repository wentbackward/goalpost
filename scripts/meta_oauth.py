"""
OAuth flow for Facebook/Instagram — gets a long-lived Page Access Token
and discovers the Instagram Business Account ID.
"""

import http.server
import os
import urllib.parse
import urllib.request
import json
import sys

APP_ID = os.environ.get("META_APP_ID", "")
APP_SECRET = os.environ.get("META_APP_SECRET", "")

if not APP_ID or not APP_SECRET:
    print("Set META_APP_ID and META_APP_SECRET environment variables")
    sys.exit(1)
REDIRECT_URI = "http://localhost:9090/callback"
SCOPES = "pages_show_list,pages_read_engagement,pages_read_user_content"

auth_url = (
    f"https://www.facebook.com/v18.0/dialog/oauth"
    f"?client_id={APP_ID}"
    f"&redirect_uri={urllib.parse.quote(REDIRECT_URI)}"
    f"&scope={SCOPES}"
    f"&response_type=code"
)

print(f"\nOpen this URL in your browser:\n\n{auth_url}\n")

code = None

class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        global code
        query = urllib.parse.urlparse(self.path).query
        params = urllib.parse.parse_qs(query)
        if "code" in params:
            code = params["code"][0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<h1>Success! You can close this tab.</h1>")
        else:
            error = params.get("error_description", ["Unknown error"])[0]
            self.send_response(400)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(f"<h1>Error: {error}</h1>".encode())

    def log_message(self, format, *args):
        pass

print("Waiting for callback on http://0.0.0.0:9090 ...")
server = http.server.HTTPServer(("0.0.0.0", 9090), Handler)
server.handle_request()

if not code:
    print("No authorization code received")
    sys.exit(1)

print("Got code. Exchanging for short-lived token...")

# Step 1: Exchange code for short-lived user token
params = urllib.parse.urlencode({
    "client_id": APP_ID,
    "client_secret": APP_SECRET,
    "redirect_uri": REDIRECT_URI,
    "code": code,
})
req = urllib.request.Request(f"https://graph.facebook.com/v18.0/oauth/access_token?{params}")
try:
    resp = json.loads(urllib.request.urlopen(req).read())
    short_token = resp["access_token"]
    print("Got short-lived token.")
except Exception as e:
    print(f"Failed to get token: {e}")
    sys.exit(1)

# Step 2: Exchange for long-lived token
print("Exchanging for long-lived token...")
params = urllib.parse.urlencode({
    "grant_type": "fb_exchange_token",
    "client_id": APP_ID,
    "client_secret": APP_SECRET,
    "fb_exchange_token": short_token,
})
req = urllib.request.Request(f"https://graph.facebook.com/v18.0/oauth/access_token?{params}")
try:
    resp = json.loads(urllib.request.urlopen(req).read())
    long_token = resp["access_token"]
    expires = resp.get("expires_in", 0)
    print(f"Got long-lived user token (expires in {expires // 86400} days).")
except Exception as e:
    print(f"Failed: {e}")
    sys.exit(1)

# Step 3: Get pages and page tokens
print("\nFetching your Pages...\n")
req = urllib.request.Request(
    f"https://graph.facebook.com/v18.0/me/accounts?access_token={long_token}"
)
try:
    resp = json.loads(urllib.request.urlopen(req).read())
    pages = resp.get("data", [])
    if not pages:
        print("No pages found. Make sure you admin a Facebook Page.")
        sys.exit(1)

    for i, page in enumerate(pages):
        print(f"  [{i+1}] {page['name']} (ID: {page['id']})")

    if len(pages) == 1:
        selected = pages[0]
    else:
        choice = int(input(f"\nSelect page [1-{len(pages)}]: ")) - 1
        selected = pages[choice]

    page_id = selected["id"]
    page_name = selected["name"]
    page_token = selected["access_token"]
    print(f"\nUsing page: {page_name} ({page_id})")
except Exception as e:
    print(f"Failed to get pages: {e}")
    sys.exit(1)

# Step 4: Get Instagram Business Account linked to this page
print("Looking for linked Instagram Business Account...")
req = urllib.request.Request(
    f"https://graph.facebook.com/v18.0/{page_id}?fields=instagram_business_account&access_token={page_token}"
)
try:
    resp = json.loads(urllib.request.urlopen(req).read())
    ig_account = resp.get("instagram_business_account", {})
    ig_id = ig_account.get("id", "")
except Exception as e:
    ig_id = ""
    print(f"Could not find Instagram account: {e}")

print(f"\n{'='*60}")
print(f"FACEBOOK_ACCESS_TOKEN={page_token}")
print(f"FACEBOOK_PAGE_ID={page_id}")
if ig_id:
    print(f"INSTAGRAM_ACCESS_TOKEN={page_token}")
    print(f"INSTAGRAM_BUSINESS_ACCOUNT_ID={ig_id}")
else:
    print("No Instagram Business Account linked to this page.")
print(f"{'='*60}")
print(f"\nPaste these into your .env file.")
