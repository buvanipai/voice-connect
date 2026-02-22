"""
Job Scraper for BhuviIT Website
Fetches job listings from https://bhuviits.com/category/jobs/ and updates the knowledge base.
Run this script manually or schedule it to keep job listings up-to-date.
"""

import requests
from bs4 import BeautifulSoup
from datetime import datetime
import re

JOBS_URL = "https://bhuviits.com/category/jobs/"
KNOWLEDGE_BASE_FILE = "app/data/knowledge_base.txt"

def fetch_jobs():
    """Fetch and parse job listings from the BhuviIT website."""
    print(f"Fetching jobs from {JOBS_URL}...")
    
    try:
        response = requests.get(JOBS_URL, timeout=10)
        response.raise_for_status()
    except Exception as e:
        print(f"❌ Error fetching jobs: {e}")
        return []
    
    soup = BeautifulSoup(response.text, 'html.parser')
    jobs = []
    
    # Find all job postings (articles with class 'post')
    job_articles = soup.find_all('article', class_='post')
    
    for article in job_articles:
        try:
            # Extract job title
            title_tag = article.find('h3')
            if not title_tag:
                continue
            
            title_link = title_tag.find('a')
            if not title_link:
                continue
                
            job_title = title_link.get_text(strip=True)
            job_url = title_link.get('href', '')
            
            # Extract date
            date_tag = article.find('time')
            job_date = date_tag.get_text(strip=True) if date_tag else "Date unknown"
            
            # Extract description (first paragraph of content)
            content_div = article.find('div', class_='entry-content')
            description = ""
            if content_div:
                first_p = content_div.find('p')
                if first_p:
                    description = first_p.get_text(strip=True)
            
            jobs.append({
                'title': job_title,
                'url': job_url,
                'date': job_date,
                'description': description
            })
            
        except Exception as e:
            print(f"⚠️ Error parsing job article: {e}")
            continue
    
    print(f"✅ Found {len(jobs)} job postings")
    return jobs


def update_knowledge_base(jobs):
    """Update the knowledge_base.txt with new job listings."""
    if not jobs:
        print("No jobs to update.")
        return
    
    # Read existing knowledge base
    try:
        with open(KNOWLEDGE_BASE_FILE, 'r') as f:
            content = f.read()
    except FileNotFoundError:
        print("❌ Knowledge base file not found!")
        return
    
    # Remove old job section if it exists
    if "CURRENT JOB OPENINGS" in content:
        # Split at the job section and keep only the part before
        base_info = content.split("CURRENT JOB OPENINGS")[0].strip()
    else:
        base_info = content.strip()
    
    # Build new job section
    job_section = f"\n\nCURRENT JOB OPENINGS (Updated: {datetime.now().strftime('%B %d, %Y')}):\n\n"
    
    for idx, job in enumerate(jobs, 1):
        job_section += f"{idx}. {job['title'].upper()}\n"
        if job['description']:
            job_section += f"   - {job['description']}\n"
        job_section += f"   - Posted: {job['date']}\n"
        if job['url']:
            job_section += f"   - More info: {job['url']}\n"
        job_section += "\n"
    
    job_section += "All positions are located in Schaumburg, IL. Candidates should be willing to work onsite or travel to the US.\n"
    job_section += "For more details visit: https://bhuviits.com/category/jobs/"
    
    # Write updated content
    new_content = base_info + job_section
    
    with open(KNOWLEDGE_BASE_FILE, 'w') as f:
        f.write(new_content)
    
    print(f"✅ Updated {KNOWLEDGE_BASE_FILE} with {len(jobs)} jobs")
    print("\n⚠️ IMPORTANT: Run 'python3 ingest.py' to update the vector database!")


def main():
    print("=" * 60)
    print("BhuviIT Jobs Scraper")
    print("=" * 60)
    
    jobs = fetch_jobs()
    
    if jobs:
        print("\nJobs found:")
        for idx, job in enumerate(jobs, 1):
            print(f"{idx}. {job['title']} (Posted: {job['date']})")
        
        update_knowledge_base(jobs)
    else:
        print("⚠️ No jobs found. The website structure may have changed.")
    
    print("\n" + "=" * 60)


if __name__ == "__main__":
    main()
