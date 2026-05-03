import os
import requests
import feedparser
import re
from datetime import datetime

# ===== 期刊RSS配置 =====
JOURNALS = {
    "NEJM": "https://www.nejm.org/rss/medical-articles.xml",
    "Lancet": "https://www.thelancet.com/rssfeed/lancet_current.xml",
    "JAMA": "https://jamanetwork.com/rss/site_3/67.xml",
    "BMJ": "https://www.bmj.com/rss/research.xml",
    "Stroke": "https://www.ahajournals.org/action/showFeed?type=etoc&feed=rss&jc=stroke",
    "Neurology": "https://n.neurology.org/rss/current.xml",
    "Circulation": "https://www.ahajournals.org/action/showFeed?type=etoc&feed=rss&jc=circulation",
}

def simple_summarize(text, max_sentences=3):
    if not text:
        return "无摘要"
    clean = re.sub('<.*?>', '', text)
    clean = clean.replace('\n', ' ').strip()
    sentences = re.split(r'(?<=[.!?])\s+', clean)
    summary = ' '.join(sentences[:max_sentences])
    if len(summary) > 800:
        summary = summary[:800] + "..."
    return summary

def fetch_papers_from_rss(rss_url, journal_name):
    papers = []
    try:
        feed = feedparser.parse(rss_url)
        for entry in feed.entries[:10]:
            papers.append({
                "title": entry.get("title", "No title"),
                "authors": entry.get("author", "Unknown"),
                "url": entry.get("link", ""),
                "published": entry.get("published", ""),
                "summary": simple_summarize(entry.get("summary", "")),
                "journal": journal_name
            })
    except Exception as e:
        print(f"Error fetching {journal_name}: {e}")
    return papers

def send_feishu(webhook_url, papers):
    """发送富文本消息到飞书"""
    
    # 构建消息内容
    date_str = datetime.now().strftime("%Y-%m-%d")
    
    # 按期刊分组构建内容
    content = []
    current_journal = ""
    
    for paper in papers:
        if paper["journal"] != current_journal:
            current_journal = paper["journal"]
            content.append([
                {"tag": "text", "text": f"\n📖 {current_journal}\n", "style": {"bold": True}}
            ])
        
        # 每条论文一个段落
        paper_text = f"📌 {paper['title']}\n👤 {paper['authors']}\n📝 {paper['summary']}\n🔗 阅读原文\n\n"
        content.append([
            {"tag": "text", "text": paper_text}
        ])
    
    # 飞书富文本消息
    message = {
        "msg_type": "post",
        "content": {
            "post": {
                "zh_cn": {
                    "title": f"📚 医学文献日报 - {date_str}",
                    "content": content
                }
            }
        }
    }
    
    # 如果论文太多，飞书消息有长度限制，分批发送
    try:
        response = requests.post(webhook_url, json=message, timeout=10)
        result = response.json()
        
        if result.get("code") == 0:
            print(f"✅ 飞书推送成功！共 {len(papers)} 篇文献")
            return True
        else:
            print(f"❌ 飞书推送失败: {result}")
            return False
            
    except Exception as e:
        print(f"❌ 请求失败: {e}")
        return False

def main():
    all_papers = []
    
    for journal, rss_url in JOURNALS.items():
        papers = fetch_papers_from_rss(rss_url, journal)
        all_papers.extend(papers)
        print(f"Fetched {len(papers)} from {journal}")
    
    # 去重
    seen_urls = set()
    unique_papers = []
    for p in all_papers:
        if p["url"] not in seen_urls:
            seen_urls.add(p["url"])
            unique_papers.append(p)
    
    print(f"\nTotal unique papers: {len(unique_papers)}")
    
    if not unique_papers:
        print("No papers found today.")
        return
    
    # 推送到飞书
    webhook = os.environ.get("FEISHU_WEBHOOK", "").strip()
    
    if not webhook:
        print("❌ 未配置 FEISHU_WEBHOOK")
        return
    
    send_feishu(webhook, unique_papers)

if __name__ == "__main__":
    main()
