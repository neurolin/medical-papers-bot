import os
import requests
import feedparser
import re
import time
import json
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
    "Practical Neurology": "https://pn.bmj.com/rss/current.xml",
    "Movement Disorders": "https://movementdisorders.onlinelibrary.wiley.com/feed",
    "Movement Disorders Clinical Practice": "https://onlinelibrary.wiley.com/feed/23308915",
}

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "").strip()

# 已推送文献记录文件
SEEN_FILE = "seen_papers.json"

def load_seen_papers():
    """加载已推送的文献ID"""
    if os.path.exists(SEEN_FILE):
        try:
            with open(SEEN_FILE, 'r', encoding='utf-8') as f:
                return set(json.load(f))
        except:
            return set()
    return set()

def save_seen_papers(seen):
    """保存已推送的文献ID"""
    with open(SEEN_FILE, 'w', encoding='utf-8') as f:
        json.dump(list(seen), f)

def fetch_papers_from_rss(rss_url, journal_name, seen_ids):
    """从RSS源获取新论文（排除已推送的）"""
    papers = []
    new_count = 0
    
    try:
        feed = feedparser.parse(rss_url)
        
        for entry in feed.entries[:15]:  # 多取一些
            # 用URL作为唯一ID
            paper_id = entry.get("link", "")
            if not paper_id:
                continue
            
            # 跳过已推送的
            if paper_id in seen_ids:
                continue
            
            new_count += 1
            
            raw_summary = entry.get("summary", "")
            clean_summary = re.sub('<.*?>', '', raw_summary).strip()
            
            papers.append({
                "title": entry.get("title", "No title"),
                "authors": entry.get("author", "Unknown"),
                "url": paper_id,
                "published": entry.get("published", ""),
                "abstract": clean_summary,
                "journal": journal_name
            })
            
    except Exception as e:
        print(f"Error fetching {journal_name}: {e}")
    
    print(f"  Total: {len(feed.entries)}, New: {new_count}")
    return papers

def ai_summary(title, abstract):
    """调用 DeepSeek API 生成完整核心摘要"""
    if not DEEPSEEK_API_KEY:
        return "【未配置API】"
    
    if not abstract or len(abstract) < 20:
        return "摘要过短，无法提炼"
    
    clean_abstract = abstract[:2000]
    
    prompt = f"""你是一位医学文献专家。请用中文概括这篇论文的核心发现，要求：
- 必须完整表达核心结论，不能半截
- 如果意思复杂，允许60字以内，但不要超过70字
- 只说结论和临床意义
- 不要背景、方法、数据细节

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
                    {"role": "system", "content": "你是医学文献摘要专家，擅长用简洁完整的中文提炼核心结论。"},
                    {"role": "user", "content": prompt}
                ],
                "max_tokens": 120,
                "temperature": 0.3
            },
            timeout=30
        )
        
        result = response.json()
        
        if "choices" in result and len(result["choices"]) > 0:
            summary = result["choices"][0]["message"]["content"].strip()
            summary = re.sub(r'\s+', ' ', summary)
            return summary
        else:
            print(f"API返回异常: {result}")
            return "【AI摘要失败】"
            
    except Exception as e:
        print(f"API调用失败: {e}")
        return "【AI摘要失败】"

def send_feishu_batch(webhook_url, papers):
    """分批发送，每批最多5篇"""
    date_str = datetime.now().strftime("%Y-%m-%d")
    
    if not papers:
        print("No new papers to send.")
        return False
    
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
    
    success = True
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
                success = False
                
        except Exception as e:
            print(f"❌ 请求失败: {e}")
            success = False
        
        if i < len(batches):
            time.sleep(1)
    
    print(f"\n✅ 推送完成！共 {len(papers)} 篇新文献")
    return success

def main():
    # 加载已推送记录
    seen_ids = load_seen_papers()
    print(f"Previously seen: {len(seen_ids)} papers")
    
    all_papers = []
    
    for journal, rss_url in JOURNALS.items():
        print(f"Fetching from {journal}...")
        papers = fetch_papers_from_rss(rss_url, journal, seen_ids)
        
        for paper in papers:
            paper["summary"] = ai_summary(paper["title"], paper["abstract"])
            time.sleep(0.5)
        
        all_papers.extend(papers)
        print(f"  Fetched {len(papers)} new from {journal}")
    
    # 去重（保险）
    unique_papers = []
    for p in all_papers:
        if p["url"] not in seen_ids:
            seen_ids.add(p["url"])
            unique_papers.append(p)
    
    print(f"\nTotal new papers: {len(unique_papers)}")
    
    if not unique_papers:
        print("No new papers today.")
        # 仍然保存记录（防止文件丢失）
        save_seen_papers(seen_ids)
        return
    
    webhook = os.environ.get("FEISHU_WEBHOOK", "").strip()
    if not webhook:
        print("❌ 未配置 FEISHU_WEBHOOK")
        return
    
    # 发送飞书
    success = send_feishu_batch(webhook, unique_papers)
    
    # 只有发送成功才保存记录（失败可重试）
    if success:
        save_seen_papers(seen_ids)
        print(f"✅ 已保存 {len(seen_ids)} 条记录")
    else:
        print("⚠️ 发送失败，未更新记录，可重试")

if __name__ == "__main__":
    main()
