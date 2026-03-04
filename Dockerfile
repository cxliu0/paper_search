# Use an official Python runtime as a parent image
FROM python:3.10-slim

# Set environment variables to prevent Python from writing .pyc files and buffering stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Set the working directory inside the container
WORKDIR /app

# Install system dependencies if needed (e.g., build tools)
# RUN apt-get update && apt-get install -y --no-install-recommends gcc && rm -rf /var/lib/apt/lists/*

# Copy the requirements file first to leverage Docker cache
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
# This includes api.py, agent.py, and the paper_agent/ directory
COPY . .

# Create the reports directory explicitly (optional, as the app creates it, but good for permissions)
RUN mkdir -p /app/reports

# Expose the port the app runs on (Hugging Face Spaces usually expects 7860 or uses $PORT)
EXPOSE 7860

# Define the command to run the application
# We bind to 0.0.0.0 so it's accessible outside the container
# We use port 7860 which is standard for HF Spaces, or you can use ENV PORT
CMD ["python", "api.py", "--host", "0.0.0.0", "--port", "7860"]
