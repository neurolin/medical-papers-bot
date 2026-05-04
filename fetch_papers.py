import os
import requests
import feedparser
import re
import time
import json
import hashlib
from datetime import datetime

# =========================
# 期刊配置：多个RSS源 + PubMed兜底
# =========================

JOURNALS = {
    "NEJM": {
        "rss": [
            "https://www.nejm.org/rss.xml",
            "https://www.nejm.org/rss/medical-articles.xml",
        ],
        "pubmed": "N Engl J Med[journal]"
    },
    "Lancet": {
        "rss": [
            "https://www.thelancet.com/rssfeed/lancet_current.xml",
        ],
        "pubmed": "Lancet[journal]"
    },
    "JAMA": {
        "rss": [
            "https://jamanetwork.com/rss/site_3.xml",
            "https://jamanetwork.com/rss/site_3/67.xml",
        ],
        "pubmed": "JAMA[journal]"
    },
    "BMJ": {
        "rss": [
            "https://www.bmj.com/rss/research.xml",
        ],
        "pubmed": "BMJ[journal]"
    },
    "Stroke": {
        "rss": [
            "https://www.ahajournals.org/action/showFeed?type=etoc&feed=rss&jc=str",
            "https://www.ahajournals.org/action/showFeed?type=etoc&feed=rss&jc=stroke",
        ],
        "pubmed": "Stroke[journal]"
    },
    "Neurology": {
        "rss": [
            "https://n.neurology.org/rss/online_first.xml",
            "https://n.neurology.org/rss/current.xml",
        ],
        "pubmed": "Neurology[journal]"
    },
    "Practical Neurology": {
        "rss": [
            "https://pn.bmj.com/rss/current.xml",
        ],
        "pubmed": "Pract Neurol[journal]"
    },
    "Movement Disorders": {
        "rss": [
            "https://movementdisorders.onlinelibrary.wiley.com/action/showFeed?type=etoc&feed=rss&jc=mds",
            "https://movementdisorders.onlinelibrary.wiley.com/feed",
        ],
        "pubmed": "Movement Disorders[journal]"
    },
    "MDCP": {
        "rss": [
            "https://movementdisordersclinicalpractice.onlinelibrary.wiley.com/action/showFeed?type=etoc&feed=rss&jc=mdc3",
            "https://onlinelibrary.wiley.com/feed/23308915",
        ],
        "pubmed": "Movement Disorders Clinical Practice[journal]"
    }
}

# =========================
# 环境变量
# =========================

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "").strip()
FEISHU_WEBHOOK = os.environ.get("FEISHU_WEBHOOK", "").strip()
SEEN_FILE = "seen_papers.json"

# =========================
# 工具函数
# =========================

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

def hash_id(text):
    """MD5哈希生成唯一ID"""
    return hashlib.md5(text.encode()).hexdigest()

def safe_fetch_rss(url):
    """带重试的RSS获取"""
    for i in range(3):
        try:
            feed = feedparser.parse(url)
            if feed.entries:
                return feed.entries
        except Exception as e:
            print(f"    RSS attempt {i+1} failed: {e}")
        time.sleep(2 * (i + 1))
    return []

def fetch_pubmed(query, seen_ids):
    """PubMed兜底：解析标题和摘要"""
    papers = []
    base = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
    
    try:
        # 搜索最近10条
        search_url = f"{base}esearch.fcgi?db=pubmed&retmode=json&term={query}&retmax=10&sort=date"
        search_response = requests.get(search_url, timeout=15)
        idlist = search_response.json().get("esearchresult", {}).get("idlist", [])
        
        if not idlist:
            return papers
        
        # 获取详情
        fetch_url = f"{base}efetch.fcgi?db=pubmed&id={','.join(idlist)}&retmode=xml"
        fetch_response = requests.get(fetch_url, timeout=15)
        xml_content = fetch_response.text
        
        # 解析每篇文章
        articles = re.findall(r'<PubmedArticle>(.*?)</PubmedArticle>', xml_content, re.DOTALL)
        
        for article in articles:
            pmid_match = re.search(r'<PMID[^>]*>(\d+)</PMID>', article)
            pmid = pmid_match.group(1) if pmid_match else ""
            url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
            
            if url in seen_ids:
                continue
            
            # 标题
            title_match = re.search(r'<ArticleTitle>(.*?)</ArticleTitle>', article, re.DOTALL)
            title = re.sub('<.*?>', '', title_match.group(1)).strip() if title_match else "No title"
            
            # 摘要 - 多层提取
            abstract = ""
            
            # 方法1: AbstractText标签
            abstract_texts = re.findall(r'<AbstractText[^>]*>(.*?)</AbstractText>', article, re.DOTALL)
            if abstract_texts:
                abstract = ' '.join([re.sub('<.*?>', ' ', t).strip() for t in abstract_texts])
            
            # 方法2: 整个Abstract
            if not abstract:
                abstract_match = re.search(r'<Abstract>(.*?)</Abstract>', article, re.DOTALL)
                if abstract_match:
                    abstract = re.sub('<.*?>', ' ', abstract_match.group(1))
                    abstract = ' '.join(abstract.split())
            
            # 方法3: OtherAbstract
            if not abstract:
                other_abstract = re.search(r'<OtherAbstract[^>]*>(.*?)</OtherAbstract>', article, re.DOTALL)
                if other_abstract:
                    abstract = re.sub('<.*?>', ' ', other_abstract.group(1))
                    abstract = ' '.join(abstract.split())
            
            # 作者
            authors = []
            author_list = re.findall(r'<Author[^>]*>.*?</Author>', article, re.DOTALL)
            for author in author_list[:3]:
                lastname = re.search(r'<LastName>(.*?)</LastName>', author)
                if lastname:
                    authors.append(lastname.group(1))
            
            authors_str = ", ".join(authors) if authors else "Unknown"
            
            papers.append({
                "id": hash_id(url + title),
                "journal": "",
                "title": title,
                "authors": authors_str,
                "summary": abstract,
                "link": url,
                "published": "",
                "source": "pubmed"
            })
            
    except Exception as e:
        print(f"    PubMed error: {e}")
    
    return papers

# =========================
# 核心抓取逻辑
# =========================

def fetch_journal(journal_name, config, seen_ids):
    """抓取单个期刊：RSS优先，PubMed兜底"""
    articles = []
    
    # 1️⃣ 逐个尝试RSS源
    for rss_url in config["rss"]:
        print(f"  Trying RSS: {rss_url}")
        entries = safe_fetch_rss(rss_url)
        
        if entries:
            print(f"    ✓ RSS success, got {len(entries)} entries")
            
            for e in entries[:15]:  # 取前15条
                link = e.get("link", "")
                title = e.get("title", "")
                paper_id = hash_id(link + title)
                
                if paper_id in seen_ids:
                    continue
                
                raw_summary = e.get("summary", "")
                clean_summary = re.sub('<.*?>', '', raw_summary).strip()
                
                articles.append({
                    "id": paper_id,
                    "journal": journal_name,
                    "title": title,
                    "authors": e.get("author", "Unknown"),
                    "summary": clean_summary,
                    "link": link,
                    "published": e.get("published", ""),
                    "source": "rss"
                })
            
            # RSS成功就跳出，不用PubMed
            break
        else:
            print(f"    ✗ RSS failed")
    
    # 2️⃣ PubMed兜底
    if not articles:
        print(f"  Falling back to PubMed...")
        pm_articles = fetch_pubmed(config["pubmed"], seen_ids)
        
        for a in pm_articles:
            a["journal"] = journal_name
        
        articles.extend(pm_articles)
        print(f"    PubMed got {len(pm_articles)} articles")
    
    return articles

# =========================
# AI摘要
# =========================

def ai_summary(title, abstract):
    """调用DeepSeek API生成核心摘要"""
    if not DEEPSEEK_API_KEY:
        return "【未配置API】"
    
    if not abstract or len(abstract) < 10:
        return "【PubMed未提供摘要，请阅读原文】"
    
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
            return "【AI摘要失败】"
            
    except Exception as e:
        return "【AI摘要失败】"

# =========================
# 飞书推送
# =========================

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
        
        paper_text = f"\n📌 {paper['title']}\n👤 {paper['authors']}\n💡 {paper['summary']}\n🔗 {paper['link']}"
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
    
    return success

# =========================
# 主流程
# =========================

def main():
    seen_ids = load_seen_papers()
    print(f"Previously seen: {len(seen_ids)} papers")
    
    all_articles = []
    
    # 逐个期刊抓取
    for journal_name, config in JOURNALS.items():
        print(f"\nFetching {journal_name}...")
        articles = fetch_journal(journal_name, config, seen_ids)
        
        # AI摘要
        for a in articles:
            a["summary"] = ai_summary(a["title"], a["summary"])
            time.sleep(0.5)
        
        all_articles.extend(articles)
        print(f"  Total new from {journal_name}: {len(articles)}")
        
        # PubMed频率限制
        if not articles or articles[0].get("source") == "pubmed":
            time.sleep(1)
    
    # 去重
    unique_papers = []
    for p in all_articles:
        if p["id"] not in seen_ids:
            seen_ids.add(p["id"])
            unique_papers.append(p)
    
    print(f"\n{'='*40}")
    print(f"Total new papers to send: {len(unique_papers)}")
    
    if not unique_papers:
        print("No new papers today.")
        save_seen_papers(seen_ids)
        return
    
    # 推送飞书
    if not FEISHU_WEBHOOK:
        print("❌ 未配置 FEISHU_WEBHOOK")
        return
    
    success = send_feishu_batch(FEISHU_WEBHOOK, unique_papers)
    
    if success:
        save_seen_papers(seen_ids)
        print(f"✅ 已保存 {len(seen_ids)} 条记录")
    else:
        print("⚠️ 发送失败，未更新记录，可重试")

if __name__ == "__main__":
    main()
