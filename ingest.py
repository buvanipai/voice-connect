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

# Add company info as line-by-line chunks
if sections[0].strip():
    company_lines = [line.strip() for line in sections[0].strip().split("\n") if line.strip()]
    documents.extend(company_lines)

# Add job section as one complete chunk
if len(sections) > 1:
    job_section = "CURRENT JOB OPENINGS" + sections[1]
    # Also add it as one big chunk
    documents.append(job_section.strip())
    
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

print(f"✅ Successfully stored {len(documents)} facts in the Vector Database!")