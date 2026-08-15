import re

file_path = '/opt/SecondBrain-Library/rss_fetcher.py'
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# Add proxy environment variables at the top of the file
proxy_code = """import os
os.environ['HTTP_PROXY'] = 'http://192.168.2.3:7890'
os.environ['HTTPS_PROXY'] = 'http://192.168.2.3:7890'
"""

if "192.168.2.3:7890" not in content:
    content = proxy_code + content
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)
    print("Proxy injected successfully.")
else:
    print("Proxy already injected.")
