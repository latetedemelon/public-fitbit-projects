# For more information, please refer to https://aka.ms/vscode-docker-python
FROM python:3.10-slim

# Keeps Python from generating .pyc files in the container
ENV PYTHONDONTWRITEBYTECODE=1

# Turns off buffering for easier container logging
ENV PYTHONUNBUFFERED=1

# Install pip requirements
COPY requirements.txt .
RUN python -m pip install --no-cache-dir -r requirements.txt

# Set working directory
WORKDIR /app

# Copy the application files
COPY ./Fitbit_Fetch.py /app
COPY ./requirements.txt /app

# Create a non-root user and set ownership of the /app directory
RUN groupadd --gid 1000 appuser && \
    useradd --uid 1000 --gid appuser --shell /bin/bash --create-home appuser && \
    chown -R appuser:appuser /app

# Switch to the non-root user
USER appuser

# Default command to run the Python script
CMD ["python", "Fitbit_Fetch.py"]
