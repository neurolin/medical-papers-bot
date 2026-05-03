import os
import requests
import time
import re
from datetime import datetime, timedelta

# ===== 期刊配置（PubMed期刊名）=====
JOURNALS = {
    "NEJM": "N Engl J Med",
    "Lancet": "Lancet",
    "JAMA": "JAMA",
    "BMJ": "BMJ",
    "Stroke": "Stroke",
    "Neurology": "Neurology",
    "Circulation": "Circulation",
    "Practical Neurology": "Pract Neurol",
    "Movement Disorders": "Mov Disord",
    "Movement Disorders Clinical Practice": "Mov Disord Clin Pract",
}

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "").strip()

def fetch_pubmed_papers(journal_name, days=7):
    """从PubMed获取指定期刊最近论文"""
    papers = []
    
    try:
        # 放宽到最近7天
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)
        
        # 简化搜索：只按期刊名搜索最近30条，不过滤日期
        query = f'"{journal_name}"[Journal]'
        
        search_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
        search_params = {
            "db": "pubmed",
            "term": query,
            "retmax": 10,
            "sort": "date",
            "retmode": "json"
        }
        
        print(f"  Search URL: {search_url}?term={query}")
        search_response = requests.get(search_url, params=search_params, timeout=30)
        search_data = search_response.json()
        
        idlist = search_data.get("esearchresult", {}).get("idlist", [])
        print(f"  Found {len(idlist)} PMIDs")
        
        if not idlist:
            return papers
        
        # 获取论文详情
        fetch_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
        fetch_params = {
            "db": "pubmed",
            "id": ",".join(idlist),
            "retmode": "xml"
        }
        
        fetch_response = requests.get(fetch_url, params=fetch_params, timeout=30)
        xml_content = fetch_response.text
        
        # 解析XML
        articles = re.findall(r'<PubmedArticle>(.*?)</PubmedArticle>', xml_content, re.DOTALL)
        print(f"  Parsed {len(articles)} articles")
        
        for article in articles:
            pmid_match = re.search(r'<PMID[^>]*>(\d+)</PMID>', article)
            pmid = pmid_match.group(1) if pmid_match else ""
            
            title_match = re.search(r'<ArticleTitle>(.*?)</ArticleTitle>', article, re.DOTALL)
            title = re.sub('<.*?>', '', title_match.group(1)).strip() if title_match else "No title"
            
            abstract_match = re.search(r'<Abstract>(.*?)</Abstract>', article, re.DOTALL)
            if abstract_match:
                abstract_text = re.sub('<.*?>', ' ', abstract_match.group(1))
                abstract = ' '.join(abstract_text.split())
            else:
                abstract = ""
            
            authors = []
            author_list = re.findall(r'<Author[^>]*>.*?</Author>', article, re.DOTALL)
            for author in author_list[:3]:
                lastname = re.search(r'<LastName>(.*?)</LastName>', author)
                if lastname:
                    authors.append(lastname.group(1))
            
            authors_str = ", ".join(authors) if authors else "Unknown"
            
            date_match = re.search(r'<PubDate>.*?<Year>(\d{4})</Year>.*?<Month>(\d{1,2}|[A-Za-z]+)</Month>.*?<Day>(\d{1,2})</Day>.*?</PubDate>', article, re.DOTALL)
            if date_match:
                pub_date = f"{date_match.group(1)}-{date_match.group(2)}-{date_match.group(3)}"
            else:
                # 尝试只取年月
                ym_match = re.search(r'<PubDate>.*?<Year>(\d{4})</Year>.*?<Month>(\d{1,2}|[A-Za-z]+)</Month>.*?</PubDate>', article, re.DOTALL)
                pub_date = f"{ym_match.group(1)}-{ym_match.group(2)}" if ym_match else ""
            
            papers.append({
                "title": title,
                "authors": authors_str,
                "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                "published": pub_date,
                "abstract": abstract,
                "journal": journal_name
            })
            
    except Exception as e:
        print(f"  Error: {e}")
        import traceback
        traceback.print_exc()
    
    return papers

def ai_summary(title, abstract):
    """调用 DeepSeek API 生成完整核心摘要"""
    if not DEEPSEEK_API_KEY:
        return "【未配置API】"
    
    if not abstract or len(abstract) < 50:
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
    
    for journal_key, journal_name in JOURNALS.items():
        print(f"Fetching from {journal_key}...")
        papers = fetch_pubmed_papers(journal_name, days=7)
        
        for paper in papers:
            paper["summary"] = ai_summary(paper["title"], paper["abstract"])
            time.sleep(0.5)
        
        all_papers.extend(papers)
        print(f"  Fetched {len(papers)} from {journal_key}")
        time.sleep(1)
    
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
