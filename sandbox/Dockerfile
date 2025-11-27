FROM python:3.12-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    libreoffice-calc \
    sqlite3 \
    xvfb \
    xdotool \
    scrot \
    x11-utils \
    imagemagick \
    openbox \
    && rm -rf /var/lib/apt/lists/*

# Set up display for GUI mode
ENV DISPLAY=:99

# Set working directory
WORKDIR /workspace

# Copy and install Python dependencies
COPY requirements.txt /tmp/
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# Create non-root user for security
RUN useradd -m -u 1000 agent && \
    chown -R agent:agent /workspace

USER agent

# Keep container running
CMD ["tail", "-f", "/dev/null"]

