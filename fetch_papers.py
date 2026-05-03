import os
import requests
import feedparser
import re
import time
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

def send_feishu_batch(webhook_url, papers):
    """分批发送，每批最多5篇"""
    date_str = datetime.now().strftime("%Y-%m-%d")
    
    # 按期刊分组
    batches = []
    current_batch = [f"📚 医学文献日报 - {date_str}\n"]
    current_count = 0
    
    current_journal = ""
    for paper in papers:
        # 新期刊开头
        if paper["journal"] != current_journal:
            current_journal = paper["journal"]
            current_batch.append(f"\n📖 {current_journal}")
        
        # 添加论文
        paper_text = f"\n📌 {paper['title']}\n👤 {paper['authors']}\n📝 {paper['summary'][:150]}...\n🔗 {paper['url']}"
        current_batch.append(paper_text)
        current_count += 1
        
        # 每5篇发一次
        if current_count >= 5:
            batches.append("\n".join(current_batch))
            current_batch = []
            current_count = 0
    
    # 最后一批
    if current_batch:
        batches.append("\n".join(current_batch))
    
    # 逐批发送
    for i, batch in enumerate(batches, 1):
        message = {
            "msg_type": "text",
            "content": {"text": batch}
        }
        
        try:
            response = requests.post(webhook_url, json=message, timeout=10)
            result = response.json()
            
            if result.get("code") == 0:
                print(f"✅ 第 {i}/{len(batches)} 批发送成功")
            else:
                print(f"❌ 第 {i} 批失败: {result}")
                
        except Exception as e:
            print(f"❌ 请求失败: {e}")
        
        # 飞书有频率限制，间隔1秒
        if i < len(batches):
            time.sleep(1)
    
    print(f"\n✅ 全部发送完成！共 {len(papers)} 篇文献，分 {len(batches)} 条消息")

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
    
    send_feishu_batch(webhook, unique_papers)

if __name__ == "__main__":
    main()
