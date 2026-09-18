#!/usr/bin/env python3
"""Configures Nginx on Azure VM to route both Project 1 and Project 2 under the HTTPS domain.
"""

import subprocess
import sys
from pathlib import Path

NGINX_CONF = Path("/etc/nginx/sites-available/marslick")

PAIMANA_BLOCK = """
    # ── Project 2: MoSPI PAIMANA Routes (SSL Port 443) ───────────────
    location /dashboard {
        proxy_pass http://127.0.0.1:8001/dashboard;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /docs {
        proxy_pass http://127.0.0.1:8001/docs;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    location /openapi.json {
        proxy_pass http://127.0.0.1:8001/openapi.json;
        proxy_set_header Host $host;
    }
"""

def main():
    if not NGINX_CONF.exists():
        print(f"[!] Error: {NGINX_CONF} not found.")
        sys.exit(1)

    content = NGINX_CONF.read_text()

    if "/dashboard" in content:
        print("[+] /dashboard route is already present in Nginx configuration.")
    else:
        print("[*] Adding PAIMANA routes to Nginx SSL configuration...")
        # Insert before the last closing brace
        last_brace_idx = content.rfind("}")
        if last_brace_idx == -1:
            print("[!] Error: Could not find closing brace in Nginx conf.")
            sys.exit(1)

        new_content = content[:last_brace_idx] + PAIMANA_BLOCK + "\n}\n"
        NGINX_CONF.write_text(new_content)
        print("[+] Nginx configuration updated successfully.")

    # Test and reload Nginx
    subprocess.run(["nginx", "-t"], check=True)
    subprocess.run(["systemctl", "reload", "nginx"], check=True)
    print("\n🎉 SUCCESS! Nginx reloaded.")
    print("👉 Project 1: https://marslick-sih.centralindia.cloudapp.azure.com/")
    print("👉 Project 2: https://marslick-sih.centralindia.cloudapp.azure.com/dashboard")
    print("👉 Project 2 Docs: https://marslick-sih.centralindia.cloudapp.azure.com/docs")

if __name__ == "__main__":
    main()
