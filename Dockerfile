# 1. Use Python 3.12 (matches your runtime.txt)
FROM python:3.12-slim

# 2. Set the folder inside the container
WORKDIR /app

# 3. Copy the dependency file first (for caching speed)
COPY requirements.txt .

# 4. Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# 5. Copy your code into the container
COPY . .

# 6. Expose the port Google expects
EXPOSE 8080

# 7. Start the app
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]