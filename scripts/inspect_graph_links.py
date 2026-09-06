import glob
import re
import os

files = glob.glob('/opt/obsidian-brain-data/Inbox/*.md')
print(f"Total Inbox files: {len(files)}")
for f in files:
    with open(f, 'r', encoding='utf-8', errors='ignore') as fp:
        content = fp.read()
    if 'AI 图谱双向关联' in content or '知识库双向关联' in content:
        print("="*60)
        print("FILE:", os.path.basename(f))
        for match in re.finditer(r'## 🔗.*', content):
            start = match.start()
            print(content[start:start+400])
