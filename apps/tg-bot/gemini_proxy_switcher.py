#!/usr/bin/env python3
import json
import urllib.request
import urllib.error
import time

CLASH_API = "http://192.168.2.3:9090"
SECRET = "ReCEVud8"
PROXY_GROUP = "GPT"
TEST_URL = "https://generativelanguage.googleapis.com"
TEST_PROXY = "http://192.168.2.3:7890"

def get_proxies():
    req = urllib.request.Request(f"{CLASH_API}/proxies")
    req.add_header("Authorization", f"Bearer {SECRET}")
    try:
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode())
            return data.get("proxies", {})
    except Exception as e:
        print(f"Error fetching proxies: {e}")
        return {}

def set_proxy(group, proxy_name):
    req = urllib.request.Request(f"{CLASH_API}/proxies/{urllib.parse.quote(group)}", method="PUT")
    req.add_header("Authorization", f"Bearer {SECRET}")
    req.add_header("Content-Type", "application/json")
    data = json.dumps({"name": proxy_name}).encode()
    try:
        with urllib.request.urlopen(req, data=data) as response:
            return response.status in (200, 204)
    except Exception as e:
        print(f"Error setting proxy {proxy_name} on {group}: {e}")
        return False

def test_gemini():
    req = urllib.request.Request(TEST_URL, method="HEAD")
    proxy_handler = urllib.request.ProxyHandler({'http': TEST_PROXY, 'https': TEST_PROXY})
    opener = urllib.request.build_opener(proxy_handler)
    try:
        resp = opener.open(req, timeout=5)
        return True
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return True
        print(f"HTTP Error: {e.code}")
        return False
    except Exception as e:
        print(f"Connection failed: {e}")
        return False

def main():
    print(f"Starting Gemini Proxy Switcher at {time.strftime('%Y-%m-%d %H:%M:%S')}")
    proxies = get_proxies()
    if not proxies:
        print("Failed to get proxies, exiting.")
        return

    candidates = []
    gpt_group = proxies.get(PROXY_GROUP)
    if gpt_group and "all" in gpt_group:
        all_nodes = gpt_group["all"]
    else:
        all_nodes = proxies.keys()

    for name in all_nodes:
        if "台湾" in name or "日本" in name or "Taiwan" in name or "Japan" in name:
            candidates.append(name)
    
    if not candidates:
        print("No Taiwan or Japan nodes found.")
        return

    print(f"Found {len(candidates)} candidate nodes.")
    success_node = None
    
    for node in candidates:
        print(f"\nTesting node: {node}")
        if not set_proxy(PROXY_GROUP, node):
            continue
        
        time.sleep(2)
        
        if test_gemini():
            print(f"[SUCCESS] {node} is working perfectly with Gemini API!")
            success_node = node
            break
        else:
            print(f"[FAIL] {node} failed to connect to Gemini API.")

    if success_node:
        print(f"\nLocked Proxy Group '{PROXY_GROUP}' to '{success_node}'.")
    else:
        print("\n[ERROR] All candidate nodes failed!")

if __name__ == "__main__":
    main()
