import os
import requests
import feedparser
import re
import time
import json
import hashlib
from datetime import datetime

# =========================
# 期刊配置
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

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "").strip()
FEISHU_WEBHOOK = os.environ.get("FEISHU_WEBHOOK", "").strip()
SEEN_FILE = "seen_papers.json"

# =========================
# 工具函数
# =========================

def load_seen_papers():
    if os.path.exists(SEEN_FILE):
        try:
            with open(SEEN_FILE, 'r', encoding='utf-8') as f:
                return set(json.load(f))
        except:
            return set()
    return set()

def save_seen_papers(seen):
    with open(SEEN_FILE, 'w', encoding='utf-8') as f:
        json.dump(list(seen), f)

def hash_id(text):
    """MD5哈希 - 用URL+标题"""
    return hashlib.md5(text.encode()).hexdigest()

def safe_fetch_rss(url):
    for i in range(3):
        try:
            feed = feedparser.parse(url)
            if feed.entries:
                return feed.entries
        except Exception as e:
            print(f"    RSS attempt {i+1} failed: {e}")
        time.sleep(2 * (i + 1))
    return []

def fetch_semantic_scholar(title):
    try:
        url = "https://api.semanticscholar.org/graph/v1/paper/search"
        params = {
            "query": title,
            "fields": "title,abstract",
            "limit": 1
        }
        response = requests.get(url, params=params, timeout=10)
        data = response.json()
        
        if data.get("data") and len(data["data"]) > 0:
            return data["data"][0].get("abstract", "")
    except Exception as e:
        print(f"    Semantic Scholar error: {e}")
    return ""

def fetch_pubmed(query, seen_ids):
    """PubMed兜底 - 改进版"""
    papers = []
    base = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
    
    try:
        # 搜索
        search_url = f"{base}esearch.fcgi?db=pubmed&retmode=json&term={query}&retmax=10&sort=date"
        print(f"    PubMed search: {search_url[:80]}...")
        search_response = requests.get(search_url, timeout=15)
        search_data = search_response.json()
        idlist = search_data.get("esearchresult", {}).get("idlist", [])
        print(f"    Found {len(idlist)} PMIDs")
        
        if not idlist:
            return papers
        
        # 获取详情
        fetch_url = f"{base}efetch.fcgi?db=pubmed&id={','.join(idlist)}&retmode=xml"
        fetch_response = requests.get(fetch_url, timeout=15)
        xml_content = fetch_response.text
        
        # 检查XML是否有效
        if "<PubmedArticle>" not in xml_content:
            print(f"    XML中没有PubmedArticle标签")
            return papers
        
        # 解析
        articles = re.findall(r'<PubmedArticle>(.*?)</PubmedArticle>', xml_content, re.DOTALL)
        print(f"    Parsed {len(articles)} articles from XML")
        
        for article in articles:
            pmid_match = re.search(r'<PMID[^>]*>(\d+)</PMID>', article)
            pmid = pmid_match.group(1) if pmid_match else ""
            url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
            
            # 标题
            title_match = re.search(r'<ArticleTitle>(.*?)</ArticleTitle>', article, re.DOTALL)
            title = re.sub('<.*?>', '', title_match.group(1)).strip() if title_match else "No title"
            
            # 用URL+标题去重
            paper_id = hash_id(url + title)
            if paper_id in seen_ids:
                continue
            
            # 摘要 - 改进提取
            abstract = ""
            
            # 方法1: AbstractText标签（最常用）
            abstract_texts = re.findall(r'<AbstractText[^>]*>(.*?)</AbstractText>', article, re.DOTALL)
            if abstract_texts:
                abstract = ' '.join([re.sub('<.*?>', ' ', t).strip() for t in abstract_texts])
                print(f"    PMID {pmid}: AbstractText found, len={len(abstract)}")
            
            # 方法2: 整个Abstract标签
            if not abstract:
                abstract_match = re.search(r'<Abstract>(.*?)</Abstract>', article, re.DOTALL)
                if abstract_match:
                    abstract = re.sub('<.*?>', ' ', abstract_match.group(1))
                    abstract = ' '.join(abstract.split())
                    print(f"    PMID {pmid}: Abstract tag found, len={len(abstract)}")
            
            # 方法3: OtherAbstract
            if not abstract:
                other_abstract = re.search(r'<OtherAbstract[^>]*>(.*?)</OtherAbstract>', article, re.DOTALL)
                if other_abstract:
                    abstract = re.sub('<.*?>', ' ', other_abstract.group(1))
                    abstract = ' '.join(abstract.split())
                    print(f"    PMID {pmid}: OtherAbstract found, len={len(abstract)}")
            
            if not abstract:
                print(f"    PMID {pmid}: No abstract found in XML")
            
            # 作者 - 只取前3个
            authors = []
            author_list = re.findall(r'<Author[^>]*>.*?</Author>', article, re.DOTALL)
            for author in author_list[:3]:
                lastname = re.search(r'<LastName>(.*?)</LastName>', author)
                firstname = re.search(r'<ForeName>(.*?)</ForeName>', author)
                
                if lastname and firstname:
                    authors.append(f"{firstname.group(1)} {lastname.group(1)}")
                elif lastname:
                    authors.append(lastname.group(1))
            
            authors_str = ", ".join(authors) if authors else "Unknown"
            
            papers.append({
                "id": paper_id,
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
        import traceback
        traceback.print_exc()
    
    return papers

# =========================
# 核心抓取逻辑
# =========================

def fetch_journal(journal_name, config, seen_ids):
    articles = []
    rss_success = False
    
    # 逐个尝试RSS源
    for rss_url in config["rss"]:
        print(f"  Trying RSS: {rss_url}")
        entries = safe_fetch_rss(rss_url)
        
        if entries:
            print(f"    ✓ RSS success, got {len(entries)} entries")
            rss_success = True
            
            for e in entries[:15]:
                link = e.get("link", "")
                title = e.get("title", "")
                paper_id = hash_id(link + title)
                
                if paper_id in seen_ids:
                    continue
                
                raw_summary = e.get("summary", "")
                clean_summary = re.sub('<.*?>', '', raw_summary).strip()
                
                # 作者处理
                authors_raw = e.get("author", "")
                if journal_name == "Stroke":
                    authors_list = [a.strip() for a in authors_raw.split(",") if a.strip()]
                    authors_clean = authors_list[0] if authors_list else "Unknown"
                else:
                    authors_list = [a.strip() for a in authors_raw.split(",") if a.strip()]
                    authors_clean = ", ".join(authors_list[:3]) if authors_list else "Unknown"
                
                articles.append({
                    "id": paper_id,
                    "journal": journal_name,
                    "title": title,
                    "authors": authors_clean,
                    "summary": clean_summary,
                    "link": link,
                    "published": e.get("published", ""),
                    "source": "rss"
                })
            
            break  # RSS成功就跳出
        else:
            print(f"    ✗ RSS failed")
    
    # 只有RSS完全失败才用PubMed
    if not rss_success:
        print(f"  Falling back to PubMed...")
        pm_articles = fetch_pubmed(config["pubmed"], seen_ids)
        
        for a in pm_articles:
            a["journal"] = journal_name
            if journal_name == "Stroke":
                authors_list = [x.strip() for x in a["authors"].split(",") if x.strip()]
                a["authors"] = authors_list[0] if authors_list else "Unknown"
        
        articles.extend(pm_articles)
        print(f"    PubMed got {len(pm_articles)} articles")
    
    return articles

# =========================
# AI摘要
# =========================

def ai_summary(title, abstract, journal_name=""):
    if not DEEPSEEK_API_KEY:
        return "【未配置API】"
    
    # 如果PubMed没摘要，尝试Semantic Scholar
    if not abstract or len(abstract) < 10:
        print(f"    尝试Semantic Scholar...")
        abstract = fetch_semantic_scholar(title)
    
    if not abstract or len(abstract) < 10:
        return "【未找到摘要，请阅读原文】"
    
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
        
        authors_text = f"\n👤 {paper['authors']}" if paper['authors'] else ""
        paper_text = f"\n📌 {paper['title']}{authors_text}\n💡 {paper['summary']}\n🔗 {paper['link']}"
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
    
    for journal_name, config in JOURNALS.items():
        print(f"\nFetching {journal_name}...")
        articles = fetch_journal(journal_name, config, seen_ids)
        
        for a in articles:
            a["summary"] = ai_summary(a["title"], a["summary"], journal_name)
            time.sleep(0.5)
        
        all_articles.extend(articles)
        print(f"  Total new from {journal_name}: {len(articles)}")
        
        if not articles or (articles and articles[0].get("source") == "pubmed"):
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
