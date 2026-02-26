"""
Job Scraper for BhuviIT Website
Fetches job listings from https://bhuviits.com/category/jobs/ and updates the knowledge base.
Run this script manually or schedule it to keep job listings up-to-date.
"""

import requests
from bs4 import BeautifulSoup
from datetime import datetime
import re

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
}

JOBS_URL = "https://bhuviits.com/category/jobs/"
KNOWLEDGE_BASE_FILE = "app/data/knowledge_base.txt"


def extract_job_requirements(text: str) -> dict:
    """
    Parse JD text to extract structured job requirements:
    - experience_required: Years of experience
    - tech_stack: Required technologies
    - visa_sponsorship: Visa/sponsorship info
    - work_arrangement: Work format (Onsite, Remote, Hybrid, etc.)
    """
    requirements = {
        "experience_required": "",
        "tech_stack": "",
        "visa_sponsorship": "",
        "work_arrangement": ""
    }
    
    text_lower = text.lower()
    
    # Extract experience requirements (e.g., "3+ years", "5 years experience")
    exp_patterns = [
        r'(\d+)\+\s*(?:years?|yrs?)',
        r'(?:minimum|at least)\s+(\d+)\s+(?:years?|yrs?)',
        r'(\d+)\s+(?:years?|yrs?)\s+(?:of\s+)?(?:experience|exp)'
    ]
    for pattern in exp_patterns:
        match = re.search(pattern, text_lower)
        if match:
            requirements["experience_required"] = f"{match.group(1)}+ years"
            break
    
    # Extract tech stack (look for common tech keywords)
    tech_keywords = [
        'python', 'java', 'javascript', 'typescript', 'react', 'vue', 'angular',
        'node.js', 'nodejs', 'aws', 'azure', 'gcp', 'google cloud',
        'sql', 'nosql', 'mongodb', 'postgresql', 'mysql',
        'docker', 'kubernetes', 'terraform', 'jenkins',
        'c++', 'c#', '.net', 'golang', 'go', 'rust',
        'php', 'ruby', 'scala', 'kotlin', 'swift',
        'html', 'css', 'sass', 'rest', 'graphql',
        'machine learning', 'ml', 'ai', 'nlp', 'deep learning',
        'data science', 'analytics', 'tableau', 'power bi'
    ]
    
    found_techs = []
    for tech in tech_keywords:
        if re.search(rf'\b{tech}\b', text_lower):
            # Capitalize first letter for display
            found_techs.append(tech.title() if len(tech) > 1 else tech.upper())
    
    if found_techs:
        requirements["tech_stack"] = ", ".join(sorted(set(found_techs)))
    
    # Extract visa/sponsorship info
    visa_keywords = {
        "H1B": "H1B sponsorship available",
        "TN visa": "TN visa sponsorship",
        "green card": "Green Card holders preferred",
        "us citizen": "US Citizen required",
        "sponsorship": "Visa sponsorship available",
        "work authorization": "Valid work authorization required",
        "ead": "EAD/H1B/Green Card holders"
    }
    
    for keyword, value in visa_keywords.items():
        if re.search(rf'\b{keyword}\b', text_lower):
            requirements["visa_sponsorship"] = value
            break
    
    # Extract work arrangement (onsite, remote, hybrid, travel)
    work_arrangement_patterns = [
        (r'\bon[- ]?site\b', "Onsite"),
        (r'\bremote\b', "Remote"),
        (r'\bhybrid\b', "Hybrid"),
        (r'willing to travel', "Travel willing"),
        (r'travel.*required', "Travel required"),
    ]
    
    for pattern, value in work_arrangement_patterns:
        if re.search(pattern, text_lower):
            requirements["work_arrangement"] = value
            break
    
    return requirements


def extract_location(text: str) -> str:
    """Extract job location from job description text.
    Returns location string or empty string if not found.
    """
    text_lower = text.lower()
    
    # Look for specific location patterns (city, state)
    location_patterns = [
        r'(?:location|located|based|work\s+in|position\s+in)[\s:]*([A-Za-z\s]+(?:,\s*(?:IL|Illinois|NY|CA|TX|CO|WA|MA|PA|FL|MI|OH|GA|NC|VA|MD|CT|NJ|LA|MO|MS|AL|TN|AK|HI|AR|NE|OK|SC|WI|MN|KS|NM|NV|UT|ID|AZ|OR|WV|DE|NH|RI|MT|ME|VT|DC|PR)))',
        r'([A-Za-z\s]+),\s*(IL|Illinois|New York|California|Texas)',
        r'(schaumburg|chicago|new york|san francisco|dallas|austin|denver|atlanta|seattle|boston)',
    ]
    
    for pattern in location_patterns:
        match = re.search(pattern, text_lower, re.IGNORECASE)
        if match:
            try:
                location = match.group(1).strip()
            except (IndexError, AttributeError):
                continue
            if location and len(location) > 2 and len(location) < 100:  # Sanity check
                # Clean up and title case the location
                location = location.replace(',', '').replace('  ', ' ').title()
                return location
    
    # If Schaumburg or Illinois mentioned, use company HQ location
    if 'schaumburg' in text_lower or 'chicago' in text_lower:
        return "Schaumburg, IL"
    
    # Default to company HQ location if no location found in job posting
    return "Schaumburg, IL"


def fetch_job_details(job_url: str) -> tuple:
    """Fetch full job description from the job detail page.
    Returns: (details_text, parsed_requirements_dict, location_string)
    """
    try:
        response = requests.get(job_url, headers=HEADERS, timeout=10)
        response.raise_for_status()
    except Exception as e:
        print(f"⚠️ Error fetching job details for {job_url}: {e}")
        return "", {}, "Schaumburg, IL"

    soup = BeautifulSoup(response.text, 'html.parser')
    
    # Try multiple selectors for content
    content_div = soup.find('div', class_='entry-content')
    if not content_div:
        # Try alternative selectors
        content_div = soup.find('div', class_='post-content')
    if not content_div:
        content_div = soup.find('article')
    if not content_div:
        # Last resort: find the main content area
        content_div = soup.find('main')
    
    if not content_div:
        print(f"   ⚠️ Could not find content div for {job_url}")
        return "", {}, "Schaumburg, IL"

    parts = []
    for tag in content_div.find_all(['p', 'li', 'pre']):
        text = tag.get_text(strip=True)
        if text and text not in parts and len(text) > 3:
            parts.append(text)

    full_text = " ".join(parts)
    
    if not full_text.strip():
        print(f"   ⚠️ No text extracted from {job_url}")
        return "", {}, "Schaumburg, IL"
    
    requirements = extract_job_requirements(full_text)
    location = extract_location(full_text)
    print(f"   ✓ Fetched {len(full_text)} chars from job detail page")
    
    return full_text, requirements, location


def fetch_jobs():
    """Fetch and parse job listings from the BhuviIT website."""
    print(f"Fetching jobs from {JOBS_URL}...")
    
    try:
        response = requests.get(JOBS_URL, headers=HEADERS, timeout=10)
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

            details = ""
            requirements = {}
            location = "Schaumburg, IL"
            if job_url:
                details, requirements, location = fetch_job_details(str(job_url))
                if not details:
                    details = description
            
            jobs.append({
                'title': job_title,
                'url': job_url,
                'date': job_date,
                'description': description,
                'details': details,
                'requirements': requirements,
                'location': location
            })
            
        except Exception as e:
            print(f"⚠️ Error parsing job article: {e}")
            continue
    
    print(f"✅ Found {len(jobs)} job postings")
    return jobs


def update_knowledge_base(jobs):
    """Update the knowledge_base.txt with new job listings and structured requirements."""
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
        base_info = content.split("CURRENT JOB OPENINGS")[0].strip()
    else:
        base_info = content.strip()
    
    # Build new job section
    job_section = f"\n\nCURRENT JOB OPENINGS (Updated: {datetime.now().strftime('%B %d, %Y')}):\n\n"
    
    for idx, job in enumerate(jobs, 1):
        job_section += f"{idx}. {job['title'].upper()}\n"
        
        # Add location
        location = job.get('location', 'Schaumburg, IL')
        job_section += f"   - Location: {location}\n"
        
        if job['description']:
            job_section += f"   - Summary: {job['description']}\n"
        
        # Add structured requirements for AI comparison
        reqs = job.get('requirements', {})
        if any(reqs.values()):
            job_section += f"   - REQUIREMENTS:\n"
            if reqs.get('experience_required'):
                job_section += f"     * Experience: {reqs['experience_required']}\n"
            if reqs.get('tech_stack'):
                job_section += f"     * Tech Stack: {reqs['tech_stack']}\n"
            if reqs.get('visa_sponsorship'):
                job_section += f"     * Visa/Sponsorship: {reqs['visa_sponsorship']}\n"
            if reqs.get('work_arrangement'):
                job_section += f"     * Work Arrangement: {reqs['work_arrangement']}\n"
        
        if job.get('details'):
            details_preview = job['details'][:300] + "..." if len(job['details']) > 300 else job['details']
            job_section += f"   - Full Details: {details_preview}\n"
        
        job_section += f"   - Posted: {job['date']}\n"
        if job['url']:
            job_section += f"   - More info: {job['url']}\n"
        job_section += "\n"
    
    job_section += "For more details and to check for additional positions, visit: https://bhuviits.com/category/jobs/"
    
    # Write updated content
    new_content = base_info + job_section
    
    with open(KNOWLEDGE_BASE_FILE, 'w') as f:
        f.write(new_content)
    
    print(f"✅ Updated {KNOWLEDGE_BASE_FILE} with {len(jobs)} jobs")
    print("\n⚠️ IMPORTANT: Run 'python3 ingest.py' to update the vector database!")


def main():
    print("=" * 60)
    print("BhuviIT Jobs Scraper with Requirement Extraction")
    print("=" * 60)
    
    jobs = fetch_jobs()
    
    if jobs:
        print("\nJobs found:")
        for idx, job in enumerate(jobs, 1):
            print(f"{idx}. {job['title']} (Posted: {job['date']}) - {job.get('location', 'Schaumburg, IL')}")
            reqs = job.get('requirements', {})
            if reqs.get('experience_required'):
                print(f"   - Experience: {reqs['experience_required']}")
            if reqs.get('tech_stack'):
                print(f"   - Tech: {reqs['tech_stack']}")
            if reqs.get('visa_sponsorship'):
                print(f"   - Visa: {reqs['visa_sponsorship']}")
            if reqs.get('work_arrangement'):
                print(f"   - Work: {reqs['work_arrangement']}")
        
        update_knowledge_base(jobs)
    else:
        print("⚠️ No jobs found. The website structure may have changed.")
    
    print("\n" + "=" * 60)


if __name__ == "__main__":
    main()
