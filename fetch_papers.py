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

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "").strip()

def ai_summary(title, abstract):
    """调用 DeepSeek API 生成50字核心摘要"""
    if not DEEPSEEK_API_KEY:
        return "【未配置API】"
    
    if not abstract or len(abstract) < 50:
        return "摘要过短，无法提炼"
    
    # 清理摘要
    clean_abstract = re.sub('<.*?>', '', abstract).replace('\n', ' ').strip()[:2000]
    
    prompt = f"""你是一位医学文献专家。请用50字以内概括这篇论文的核心发现，要求：
- 只说结论和意义
- 不要背景、方法、数据细节
- 用中文表达

标题：{title}
摘要：{clean_abstract}

核心发现："""
    
    try:
        response = requests.post(
            "https://api.deepseek.com/chat/completions",
            headers={
                "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": "deepseek-chat",
                "messages": [
                    {"role": "system", "content": "你是医学文献摘要专家，擅长提炼核心结论。"},
                    {"role": "user", "content": prompt}
                ],
                "max_tokens": 100,
                "temperature": 0.3
            },
            timeout=30
        )
        
        result = response.json()
        
        if "choices" in result and len(result["choices"]) > 0:
            summary = result["choices"][0]["message"]["content"].strip()
            # 限制50字
            if len(summary) > 55:
                summary = summary[:50] + "..."
            return summary
        else:
            print(f"API返回异常: {result}")
            return "【AI摘要失败】"
            
    except Exception as e:
        print(f"API调用失败: {e}")
        return "【AI摘要失败】"

def fetch_papers_from_rss(rss_url, journal_name):
    papers = []
    try:
        feed = feedparser.parse(rss_url)
        for entry in feed.entries[:10]:
            title = entry.get("title", "No title")
            abstract = entry.get("summary", "")
            
            # 调用AI生成摘要
            summary = ai_summary(title, abstract)
            
            papers.append({
                "title": title,
                "authors": entry.get("author", "Unknown"),
                "url": entry.get("link", ""),
                "published": entry.get("published", ""),
                "summary": summary,
                "journal": journal_name
            })
            
            # API有频率限制，间隔一下
            time.sleep(0.5)
            
    except Exception as e:
        print(f"Error fetching {journal_name}: {e}")
    return papers

def send_feishu_batch(webhook_url, papers):
    """分批发送，每批最多5篇"""
    date_str = datetime.now().strftime("%Y-%m-%d")
    
    batches = []
    current_batch = [f"📚 医学文献日报 - {date_str}\n"]
    current_count = 0
    
    current_journal = ""
    for paper in papers:
        if paper["journal"] != current_journal:
            current_journal = paper["journal"]
            current_batch.append(f"\n📖 {current_journal}")
        
        paper_text = f"\n📌 {paper['title']}\n👤 {paper['authors']}\n💡 {paper['summary']}\n🔗 {paper['url']}"
        current_batch.append(paper_text)
        current_count += 1
        
        if current_count >= 5:
            batches.append("\n".join(current_batch))
            current_batch = []
            current_count = 0
    
    if current_batch:
        batches.append("\n".join(current_batch))
    
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
        
        if i < len(batches):
            time.sleep(1)
    
    print(f"\n✅ 全部完成！共 {len(papers)} 篇，分 {len(batches)} 条消息")

def main():
    all_papers = []
    
    for journal, rss_url in JOURNALS.items():
        papers = fetch_papers_from_rss(rss_url, journal)
        all_papers.extend(papers)
        print(f"Fetched {len(papers)} from {journal}")
    
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
