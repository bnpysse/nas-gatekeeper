import os
import sys
sys.path.append('/opt/SecondBrain-Library')
import libsql_client
from dotenv import load_dotenv
import glob

load_dotenv('/opt/SecondBrain-Library/.env', override=True)

url = os.environ.get("TURSO_DATABASE_URL")
auth_token = os.environ.get("TURSO_AUTH_TOKEN")
client = libsql_client.create_client_sync(url=url, auth_token=auth_token)

# 1. Clear recent reddit items from DB
client.execute("DELETE FROM processed_items WHERE source = 'reddit'")
client.close()
print("Cleared Reddit history from Turso DB.")

# 2. Delete the malformed markdown files
vault_path = "/opt/SecondBrain-Quartz/content/notes/Auto_Clippings"
files_to_delete = glob.glob(os.path.join(vault_path, "*Browser MCP*")) + glob.glob(os.path.join(vault_path, "*AMD's upcoming Zen 6*"))
for f in files_to_delete:
    try:
        os.remove(f)
        print(f"Deleted: {f}")
    except Exception as e:
        print(f"Error deleting {f}: {e}")
