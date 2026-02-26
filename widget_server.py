#!/usr/bin/env python3
"""
Simple HTTP server for the desktop widget.
Proxies API requests to avoid CORS issues.
"""

import http.server
import json
import socketserver
import ssl
import urllib.request
from urllib.parse import urlparse, parse_qs

PORT = 8765
API_URL = "https://gmail-obsidian-sync-729716d2143d.herokuapp.com/dashboard/stats"


class WidgetHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/api/stats':
            # Proxy API request
            try:
                # Create SSL context that doesn't verify certificates (for local development)
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE

                response = urllib.request.urlopen(API_URL, timeout=5, context=ctx)
                data = response.read()

                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(data)
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                error = json.dumps({"error": str(e)})
                self.wfile.write(error.encode())

        elif self.path == '/' or self.path == '/widget':
            # Serve the widget HTML
            self.path = '/desktop_widget_local.html'
            return super().do_GET()

        else:
            return super().do_GET()

    def log_message(self, format, *args):
        # Suppress log messages for cleaner output
        pass


def main():
    with socketserver.TCPServer(("", PORT), WidgetHandler) as httpd:
        print(f"🚀 Widget Server Running!")
        print(f"📊 Open: http://localhost:{PORT}/widget")
        print(f"🔄 Auto-refreshes every 10 seconds")
        print(f"❌ Press Ctrl+C to stop")
        print()

        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n\n👋 Widget server stopped")


if __name__ == "__main__":
    main()
