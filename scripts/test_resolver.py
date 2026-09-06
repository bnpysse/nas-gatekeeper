import glob
import os
import re

inbox_files = glob.glob('/opt/obsidian-brain-data/Inbox/*.md')
clippings_files = glob.glob('/opt/obsidian-brain-data/Auto_Clippings/*.md')
all_files = inbox_files + clippings_files

def normalize(s):
    s = re.sub(r'^\[.*?\]', '', s)
    s = re.sub(r'^(Auto_简报_|Raw_翻译_)', '', s)
    s = re.sub(r'(_简报|_全翻译)$', '', s)
    s = re.sub(r'_2026\d+_\d+', '', s)
    s = re.sub(r'#[^\s#]+', '', s)
    # Remove tags like _股票_股民交流...
    s = re.sub(r'(_股票|_股民交流|_投资理财|_资讯|_纳斯达克|_存储|_AI|_芯片|_cpo|_英伟达|_硅光|_asic|_els|_nand)+', '', s)
    s = re.sub(r'[_\s:：?？!！#（）()\.,，。、《》“”\'\-+~…]+', '', s)
    return s.lower()

file_map = {}
for f in all_files:
    stem = os.path.splitext(os.path.basename(f))[0]
    norm = normalize(stem)
    if norm not in file_map:
        file_map[norm] = f

test_links = [
    "老股民：今天的大跌，是趋势反转？",
    "老股民：这波行情走得极其磨人！恰恰是新一轮大牛市的前兆？",
    "老股民：券商迟迟不爆发，难道只看业绩？",
    "老股民:如何简单估算主力成本？一个实用的判断方法",
    "The Maradona Theory of Interest Rates_简报",
    "明紧暗松，收割突然转向，美国印钞机轰鸣模式已经挂档",
    "A股，一个大轮回又开始了（珍惜收藏） #股票#股民交流#投资理财#资讯#纳斯达克",
    "股价涨跌根本不重要！真正的投资逻辑 99% 的人不懂",
    "美称将对伊发动经济战",
    "中美竞争脱离传统经贸窠臼加速迭代_全翻译",
    "长江存储值得看的行业趋势和数据",
    "为什么不买存储股？大佬们：涨得越狠，我越担心",
    "美扩大长债回购规模，怎么利好黄金？",
    "Run It Hot, Yet Again_简报"
]

for tl in test_links:
    ntl = normalize(tl)
    matched = None
    if ntl in file_map:
        matched = file_map[ntl]
    else:
        for k, v in file_map.items():
            if len(ntl) >= 4 and (ntl in k or k in ntl):
                matched = v
                break
    print(f"{tl} -> {os.path.basename(matched) if matched else 'NOT FOUND'}")
