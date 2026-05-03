import os
import requests
import feedparser
from datetime import datetime, timedelta
from notion_client import Client

# ===== 配置区域（修改这里）=====
JOURNALS = {
    "NEJM": "https://www.nejm.org/rss/medical-articles.xml",
    "Lancet": "https://www.thelancet.com/rssfeed/lancet_current.xml",
    "JAMA": "https://jamanetwork.com/rss/site_3/67.xml",
    "BMJ": "https://www.bmj.com/rss/research.xml",
    # 可以继续添加其他期刊RSS
}

# 关键词过滤（只保留含这些词的论文，留空则不过滤）
KEYWORDS = ["stroke", "cardiovascular", "hypertension", "diabetes", "ischemia"]

# ==============================

def get_notion_client():
    return Client(auth=os.environ["NOTION_TOKEN"])

def fetch_papers_from_rss(rss_url, journal_name):
    """从RSS源获取论文"""
    papers = []
    try:
        feed = feedparser.parse(rss_url)
        for entry in feed.entries[:5]:  # 每个期刊取最近5篇
            paper = {
                "title": entry.get("title", "No title"),
                "authors": entry.get("author", "Unknown"),
                "url": entry.get("link", ""),
                "published": entry.get("published", ""),
                "summary": entry.get("summary", "")[:500],  # 摘要前500字
                "journal": journal_name
            }
            papers.append(paper)
    except Exception as e:
        print(f"Error fetching {journal_name}: {e}")
    return papers

def filter_by_keywords(papers, keywords):
    """按关键词过滤"""
    if not keywords:
        return papers
    filtered = []
    for paper in papers:
        text = f"{paper['title']} {paper['summary']}".lower()
        if any(kw.lower() in text for kw in keywords):
            filtered.append(paper)
    return filtered

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
    db_id = os.environ["NOTION_DATABASE_ID"]
    
    all_papers = []
    
    # 获取所有期刊论文
    for journal, rss_url in JOURNALS.items():
        papers = fetch_papers_from_rss(rss_url, journal)
        all_papers.extend(papers)
        print(f"Fetched {len(papers)} from {journal}")
    
    # 关键词过滤
    filtered = filter_by_keywords(all_papers, KEYWORDS)
    print(f"Filtered: {len(filtered)}/{len(all_papers)} papers match keywords")
    
    # 去重（按URL）
    seen_urls = set()
    unique_papers = []
    for p in filtered:
        if p["url"] not in seen_urls:
            seen_urls.add(p["url"])
            unique_papers.append(p)
    
    # 添加到Notion
    added_count = 0
    for paper in unique_papers:
        if add_to_notion(notion, db_id, paper):
            added_count += 1
    
    print(f"\nDone! Added {added_count} papers to Notion.")

if __name__ == "__main__":
    main()
