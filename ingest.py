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
collection = chroma_client.get_or_create_collection(
    name="bhuvi_knowledge",
    embedding_function=sentence_transformer_ef
)

# 5. Read the Text File
with open(DATA_PATH, "r") as f:
    # Split by lines and remove empty ones
    documents = [line.strip() for line in f.readlines() if line.strip()]

# 6. Generate IDs (just numbers 1, 2, 3...)
ids = [str(i) for i in range(len(documents))]

# 7. Add to Database (This does the heavy lifting: Text -> Vectors)
collection.add(
    documents=documents,
    ids=ids
)

print(f"✅ Successfully stored {len(documents)} facts in the Vector Database!")