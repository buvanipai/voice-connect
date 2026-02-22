# 1. Use Python 3.12 (matches your runtime.txt)
FROM python:3.12-slim

# 2. Set the folder inside the container
WORKDIR /app

# 3. Copy the dependency file first (for caching speed)
COPY requirements.txt .

RUN pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cpu

# 4. Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# 5. Copy your code into the container
COPY . .

# 6. Generate vector database from knowledge base
RUN python ingest.py

# 7. Expose the port Google expects
EXPOSE 8080

# 8. Start the app
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]