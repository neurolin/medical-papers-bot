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
    """发送文本消息到飞书"""
    
    date_str = datetime.now().strftime("%Y-%m-%d")
    
    # 构建文本内容
    lines = [f"📚 医学文献日报 - {date_str}\n"]
    
    current_journal = ""
    for paper in papers:
        if paper["journal"] != current_journal:
            current_journal = paper["journal"]
            lines.append(f"\n📖 {current_journal}")
        
        # 飞书文本消息，不要复杂格式
        lines.append(f"📌 {paper['title']}")
        lines.append(f"👤 {paper['authors']}")
        lines.append(f"📝 {paper['summary'][:200]}...")  # 限制长度
        lines.append(f"🔗 {paper['url']}")
        lines.append("")  # 空行分隔
    
    # 合并文本，注意飞书限制4096字符
    full_text = "\n".join(lines)
    if len(full_text) > 4000:
        full_text = full_text[:4000] + "\n\n...(内容过长，已截断)"
    
    # 飞书文本消息格式
    message = {
        "msg_type": "text",
        "content": {
            "text": full_text
        }
    }
    
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
    
    webhook = os.environ.get("FEISHU_WEBHOOK", "").strip()
    if not webhook:
        print("❌ 未配置 FEISHU_WEBHOOK")
        return
    
    send_feishu(webhook, unique_papers)

if __name__ == "__main__":
    main()
