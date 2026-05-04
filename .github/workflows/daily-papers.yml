name: Daily Medical Papers

on:
  schedule:
    - cron: '0 0 * * *'  # UTC 00:00 = 北京 08:00
  workflow_dispatch:

jobs:
  fetch-papers:
    runs-on: ubuntu-latest
    
    steps:
      - uses: actions/checkout@v4
      
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
          
      - name: Install dependencies
        run: |
          pip install requests feedparser beautifulsoup4
          
      - name: Run paper fetcher
        env:
          FEISHU_WEBHOOK: ${{ secrets.FEISHU_WEBHOOK }}
          DEEPSEEK_API_KEY: ${{ secrets.DEEPSEEK_API_KEY }}
        run: python fetch_papers.py
          
      - name: Upload seen papers artifact
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: seen-papers
          path: seen_papers.json
