# Use an official Python runtime as a parent image
FROM python:3.11-slim

# Install build tools and curl
RUN apt-get update && apt-get install -y build-essential python3-dev curl

# Install uv and make it available in PATH
RUN mkdir -p /root/.local/bin && \
    curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:${PATH}"

# Set up working directory
WORKDIR /app

# Copy the Python scripts and the configuration files into the container
COPY pyproject.toml ./
COPY drawio2clab.py ./
COPY clab2drawio.py ./
COPY entrypoint.sh ./
COPY styles/ ./styles/
COPY core/ ./core/
COPY cli/ ./cli/

# Install dependencies using uv
RUN /root/.local/bin/uv pip sync --system pyproject.toml

# Make the entrypoint script executable
RUN chmod +x /app/entrypoint.sh

# Set the working directory for running the application
WORKDIR /data
ENV APP_BASE_DIR=/app

# Use the entrypoint script to handle script execution
ENTRYPOINT ["/app/entrypoint.sh"]