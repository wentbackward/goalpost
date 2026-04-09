"""
Quick OAuth 2.0 flow to get a LinkedIn access token.
Run this locally, open the URL it prints, authorize, and it captures the token.
"""

import http.server
import ssl
import urllib.parse
import webbrowser
import sys
import os

CLIENT_ID = os.environ.get("LINKEDIN_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("LINKEDIN_CLIENT_SECRET", "")
REDIRECT_URI = os.environ.get("REDIRECT_URI", "https://localhost:9090/callback")
SCOPES = "openid profile email w_member_social"

if not CLIENT_ID or not CLIENT_SECRET:
    print("Set LINKEDIN_CLIENT_ID and LINKEDIN_CLIENT_SECRET environment variables")
    sys.exit(1)

auth_url = (
    f"https://www.linkedin.com/oauth/v2/authorization"
    f"?response_type=code"
    f"&client_id={CLIENT_ID}"
    f"&redirect_uri={urllib.parse.quote(REDIRECT_URI)}"
    f"&scope={urllib.parse.quote(SCOPES)}"
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
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"No code received")

    def log_message(self, format, *args):
        pass

cert_dir = os.path.join(os.path.dirname(__file__), "..", "certs")
certfile = os.path.join(cert_dir, "server.crt")
keyfile = os.path.join(cert_dir, "server.key")

server = http.server.HTTPServer(("0.0.0.0", 9090), Handler)
if os.path.exists(certfile) and os.path.exists(keyfile):
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(certfile, keyfile)
    server.socket = ctx.wrap_socket(server.socket, server_side=True)
    print("Waiting for callback on https://0.0.0.0:9090 ...")
else:
    print("Warning: No TLS certs found, running plain HTTP")
    print("Waiting for callback on http://0.0.0.0:9090 ...")
server.handle_request()

if not code:
    print("No authorization code received")
    sys.exit(1)

print(f"\nGot authorization code. Exchanging for token...")

import urllib.request
import json

data = urllib.parse.urlencode({
    "grant_type": "authorization_code",
    "code": code,
    "redirect_uri": REDIRECT_URI,
    "client_id": CLIENT_ID,
    "client_secret": CLIENT_SECRET,
}).encode()

req = urllib.request.Request(
    "https://www.linkedin.com/oauth/v2/accessToken",
    data=data,
    headers={"Content-Type": "application/x-www-form-urlencoded"},
)

try:
    resp = urllib.request.urlopen(req)
    result = json.loads(resp.read())
    token = result.get("access_token", "")
    expires_in = result.get("expires_in", 0)
    days = expires_in // 86400

    print(f"\n{'='*60}")
    print(f"ACCESS TOKEN (expires in {days} days):")
    print(f"\n{token}\n")
    print(f"{'='*60}")
    print(f"\nPaste this into LINKEDIN_ACCESS_TOKEN in your .env file")
except Exception as e:
    print(f"Token exchange failed: {e}")
    sys.exit(1)
