import os
import requests
import feedparser
import re
from datetime import datetime
from notion_client import Client

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
    """提取前几句作为摘要总结"""
    if not text:
        return "无摘要"
    
    clean = re.sub('<.*?>', '', text)
    clean = clean.replace('\n', ' ').strip()
    
    sentences = re.split(r'(?<=[.!?])\s+', clean)
    summary = ' '.join(sentences[:max_sentences])
    
    if len(summary) > 800:
        summary = summary[:800] + "..."
    
    return summary

def get_notion_client():
    token = os.environ["NOTION_TOKEN"]
    # 清理token中的非法字符（换行、空格等）
    token = token.strip()
    return Client(auth=token)

def fetch_papers_from_rss(rss_url, journal_name):
    """从RSS源获取论文"""
    papers = []
    try:
        feed = feedparser.parse(rss_url)
        for entry in feed.entries[:10]:
            raw_summary = entry.get("summary", "")
            
            paper = {
                "title": entry.get("title", "No title"),
                "authors": entry.get("author", "Unknown"),
                "url": entry.get("link", ""),
                "published": entry.get("published", ""),
                "raw_summary": raw_summary,
                "summary": simple_summarize(raw_summary),
                "journal": journal_name
            }
            papers.append(paper)
    except Exception as e:
        print(f"Error fetching {journal_name}: {e}")
    return papers

def add_to_notion(notion, database_id, paper):
    """添加论文到Notion数据库"""
    try:
        notion.pages.create(
            parent={"database_id": database_id},
            properties={
                "Title": {"title": [{"text": {"content": paper["title"]}}]},
                "Journal": {"select": {"name": paper["journal"]}},
                "Authors": {"rich_text": [{"text": {"content": paper["authors"][:100]}}]},
                "URL": {"url": paper["url"]},
                "Published": {"date": {"start": datetime.now().isoformat()}},
                "Summary": {"rich_text": [{"text": {"content": paper["summary"]}}]},
                "Status": {"select": {"name": "New"}}
            }
        )
        print(f"Added: {paper['title'][:50]}...")
        return True
    except Exception as e:
        print(f"Error adding to Notion: {e}")
        return False

def main():
    notion = get_notion_client()
    db_id = os.environ["NOTION_DATABASE_ID"].strip()  # 清理可能的空格
    
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
    
    # 添加到Notion
    added_count = 0
    for paper in unique_papers:
        if add_to_notion(notion, db_id, paper):
            added_count += 1
    
    print(f"\nDone! Added {added_count} papers to Notion.")

if __name__ == "__main__":
    main()
