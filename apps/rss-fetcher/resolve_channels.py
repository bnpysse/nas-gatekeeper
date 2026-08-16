import urllib.request
import re

channels = [
    ("小lin说", "https://www.youtube.com/@xiao_lin_shuo"),
    ("巫师财经", "https://www.youtube.com/@%E5%B7%AB%E5%B8%88%E8%B4%A2%E7%BB%8F"),
    ("王剑每日观察", "https://www.youtube.com/@wongkim728"),
    ("Principles by Ray Dalio", "https://www.youtube.com/@PrinciplesbyRayDalio"),
    ("Patrick Boyle", "https://www.youtube.com/@PatrickBoyleOnFinance"),
    ("The Plain Bagel", "https://www.youtube.com/@ThePlainBagel"),
    ("Ben Felix", "https://www.youtube.com/@BenFelixCSI"),
    ("Economics Explained", "https://www.youtube.com/@EconomicsExplained"),
    ("All-In Podcast", "https://www.youtube.com/@allin"),
    ("Visual Economik CN", "https://www.youtube.com/@VisualEconomikCN"),
    ("Forward Guidance", "https://www.youtube.com/@ForwardGuidance"),
    ("Real Vision", "https://www.youtube.com/@RealVisionFinance"),
    ("不二家（边风炜/冬哥）", "https://www.youtube.com/@fujiya_financial"),
    ("Bloomberg", "https://www.youtube.com/@Bloomberg"),
    ("CNBC Television", "https://www.youtube.com/@CNBCtelevision")
]

opener = urllib.request.build_opener(urllib.request.ProxyHandler({"http": "http://192.168.2.3:7890", "https": "http://192.168.2.3:7890"}))

for name, url in channels:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        html = opener.open(req, timeout=12).read().decode("utf-8", errors="ignore")
        m = re.search(r'itemprop="channelId"\s+content="(UC[\w-]{22})"', html) or \
            re.search(r'channelId":"(UC[\w-]{22})"', html) or \
            re.search(r'/channel/(UC[\w-]{22})', html)
        cid = m.group(1) if m else "NOT FOUND"
        print(f"{name} | {cid} | https://www.youtube.com/feeds/videos.xml?channel_id={cid}")
    except Exception as e:
        print(f"{name} ERR: {e}")
