import os
import chromadb
from chromadb.utils import embedding_functions

# 1. Setup the Database (It will create a folder called 'chroma_db')
DATA_PATH = "app/data/knowledge_base.txt"
DB_PATH = "chroma_db"

print(f"Loading knowledge from {DATA_PATH}...")

# 2. Connect to Chroma (Local Mode)
chroma_client = chromadb.PersistentClient(path=DB_PATH)

# 3. Use a Free, High-Speed Embedding Model
sentence_transformer_ef = embedding_functions.SentenceTransformerEmbeddingFunction(
    model_name="all-MiniLM-L6-v2"
)

# 4. Create (or Reset) the Collection
# Delete old collection if it exists to avoid duplicates
try:
    chroma_client.delete_collection(name="bhuvi_knowledge")
    print("Deleted old collection")
except:
    pass

collection = chroma_client.get_or_create_collection(
    name="bhuvi_knowledge",
    embedding_function=sentence_transformer_ef #type: ignore
)

# 5. Read the Text File and create smart chunks
with open(DATA_PATH, "r") as f:
    content = f.read()

# Split into sections: company info and jobs
sections = content.split("CURRENT JOB OPENINGS")

documents = []

# --- COMPANY INFO SECTION ---
# Add company info as individual descriptive chunks (better for RAG retrieval)
if sections[0].strip():
    company_lines = [line.strip() for line in sections[0].strip().split("\n") if line.strip()]
    documents.extend(company_lines)

# Add explicit location and relocation info for better retrieval
documents.extend([
    "Bhuvi IT Solutions is headquartered in Schaumburg, IL 60173.",
    "All job positions are located in Schaumburg, IL.",
    "Candidates are required to be willing to work onsite or travel to the US for available positions.",
    "The company offers TN Visa sponsorship and can deploy engineers quickly to the US.",
    "Nearshore delivery using talent from Mexico, Chile, and Argentina is a core offering."
])

# --- JOB LISTINGS SECTION ---
# Parse individual jobs from the section and create structured chunks
if len(sections) > 1:
    job_section = sections[1]
    
    # Split by lines and group jobs
    lines = [line.strip() for line in job_section.split("\n") if line.strip()]
    
    current_job = []
    for line in lines:
        # Detect job titles (start with number + period)
        if line and line[0].isdigit() and "." in line[:3]:
            # Save previous job if exists
            if current_job:
                job_text = "\n".join(current_job).strip()
                if job_text:
                    documents.append(job_text)
            current_job = [line]
        else:
            if current_job:
                current_job.append(line)
    
    # Add the last job
    if current_job:
        job_text = "\n".join(current_job).strip()
        if job_text:
            documents.append(job_text)
    
    # Add summary chunks for each role mentioning location
    role_keywords = ["Software Engineer", "Systems Analyst", "UX Designer", "Graphic Designer", "Program Manager"]
    for role in role_keywords:
        documents.append(f"{role} position available in Schaumburg, IL. Requires willingness to work onsite or travel to the US.")
    
    # Additionally, split individual job entries for better retrieval
    job_lines = sections[1].strip().split("\n")
    current_job = []
    for line in job_lines:
        if line.strip().startswith(tuple(str(i) + "." for i in range(1, 10))):
            # Found a new job entry
            if current_job:
                documents.append("\n".join(current_job))
            current_job = [line]
        elif line.strip():
            current_job.append(line)
    
    # Add last job
    if current_job:
        documents.append("\n".join(current_job))

# 6. Generate IDs (just numbers 1, 2, 3...)
ids = [str(i) for i in range(len(documents))]

# 7. Add to Database (This does the heavy lifting: Text -> Vectors)
collection.add(
    documents=documents,
    ids=ids
)

print(f"✅ Successfully stored {len(documents)} chunks in the Vector Database!")

# 8. TEST RETRIEVAL - Verify location and job information is retrievable
print("\n" + "="*60)
print("TESTING RAG RETRIEVAL - Verifying Location Context")
print("="*60)

test_queries = [
    "What is the job location?",
    "Where are positions based in Illinois?",
    "Do I need to relocate to work here?",
    "Tell me about Software Engineer roles",
    "What UX positions are available?",
    "I am in Mexico, can I work remotely?",
]

for query in test_queries:
    results = collection.query(query_texts=[query], n_results=2)
    print(f"\n📍 Query: '{query}'")
    print(f"   Top match: {results['documents'][0][0][:80]}...")
