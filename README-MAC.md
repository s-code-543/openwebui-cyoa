# LLM CYOA - macOS Setup Guide

This guide documents the macOS (Apple Silicon) setup for the LLM Choose Your Own Adventure game server.

> **Note:** This project now uses centralized nginx routing. See [NGINX-MIGRATION.md](NGINX-MIGRATION.md) for the new architecture.

---

## Prerequisites

- macOS with Apple Silicon (M1/M2/M3)
- [Homebrew](https://brew.sh) installed
- **Xcode** from the App Store - Required for Core ML model generation
  - After installing, open Xcode and accept the license agreement
  - Or run: `sudo xcodebuild -license accept`
- **Docker Desktop** for Mac
  - Install via [Docker Website](https://www.docker.com/products/docker-desktop/) or `brew install --cask docker`
  - Ensure it is running before starting the stack
- **Shared Docker Network** - Create once:
  ```bash
  docker network create stargate-shared --driver bridge
  ```

---

## Whisper.cpp STT Server Setup

The speech-to-text service runs natively to access the Neural Engine.

### 1. Install Dependencies
```bash
brew install cmake ffmpeg
```

### 2. Clone and Build whisper.cpp
```bash
cd /Users/$(whoami)
git clone https://github.com/ggerganov/whisper.cpp.git
cd whisper.cpp

# Download the model
sh ./models/download-ggml-model.sh large-v3-turbo

# Build with Core ML and FFmpeg support
mkdir -p build && cd build
cmake -DWHISPER_COREML=1 -DWHISPER_FFMPEG=1 ..
cmake --build . --config Release -j

# Generate Core ML model for Neural Engine (requires Xcode installed)
cd ~/whisper.cpp
./models/generate-coreml-model.sh large-v3-turbo
```

**Note:** The `generate-coreml-model.sh` script requires Xcode to be installed and its license accepted. If you see errors about missing developer tools, install Xcode from the App Store first.

### 3. Configure Background Service (LaunchAgent)

Create the service file to auto-start Whisper server on boot:

```bash
cat <<EOF > ~/Library/LaunchAgents/com.whisper.server.plist
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.whisper.server</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    </dict>
    <key>ProgramArguments</key>
    <array>
        <string>/Users/$(whoami)/whisper.cpp/build/bin/whisper-server</string>
        <string>-m</string>
        <string>/Users/$(whoami)/whisper.cpp/models/ggml-large-v3-turbo.bin</string>
        <string>--port</string>
        <string>10300</string>
        <string>--host</string>
        <string>0.0.0.0</string>
        <string>--convert</string>
        <string>--inference-path</string>
        <string>/v1/audio/transcriptions</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>WorkingDirectory</key>
    <string>/Users/$(whoami)/whisper.cpp</string>
    <key>StandardOutPath</key>
    <string>/Users/$(whoami)/whisper.cpp/whisper_server.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/$(whoami)/whisper.cpp/whisper_server_err.log</string>
</dict>
</plist>
EOF
```

### 4. Start and Manage the Service

```bash
# Load the server
launchctl load ~/Library/LaunchAgents/com.whisper.server.plist

# Check if running
launchctl list | grep whisper

# Restart after changes
launchctl kickstart -k gui/$(id -u)/com.whisper.server

# Unload (stop permanently)
launchctl unload ~/Library/LaunchAgents/com.whisper.server.plist
```

### 5. Test Whisper Server

```bash
cd ~/whisper.cpp
curl --request POST \
  --url http://localhost:10300/v1/audio/transcriptions \
  --header 'Content-Type: multipart/form-data' \
  --form file=@samples/jfk.wav \
  --form model=large-v3-turbo
```

You should see JSON with the transcription of JFK's speech.

---

## SSL Setup

Tips for using this app with subdomain based routing from centralized docker network nginx

### 1. Create SSL Certificates

Generate self-signed certificates for HTTPS access:

```bash
cd /Users/$(whoami)/nginx
mkdir -p ssl

openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout ssl/openwebui+cyoa-key.pem \
  -out ssl/openwebui+cyoa.pem \
  -subj "/C=US/ST=State/L=City/O=Home/CN=cyoa.mac.stargate.lan" \
  -addext "subjectAltName=DNS:cyoa.mac.stargate.lan,DNS:openwebui.mac.stargate.lan,DNS:*.stargate.lan,DNS:localhost,IP:127.0.0.1"
```

### 2. Set Environment Variables

Create a `.env` file with your API keys:

```bash
cd /Users/yolo/llm-cyoa
cat <<EOF > .env
ANTHROPIC_API_KEY=sk-ant-your-key-here
EOF
```

### 3. Start the Services

**Important:** Start nginx gateway first, then individual services.

```bash
# 1. Start central nginx gateway (handles TLS termination)
cd /Users/$(whoami)/nginx
docker compose up -d

# 2. Start CYOA game server
cd /Users/$(whoami)/llm-cyoa
docker compose -f docker-compose.mac.yml up -d

# Watch logs (optional)
docker compose -f docker-compose.mac.yml logs -f
```

### 4. Access the Game

- **HTTPS (recommended):** https://cyoa.mac.stargate.lan
- **Direct HTTP (debugging):** http://localhost:8001

Accept the self-signed certificate warning in your browser on first visit.

---

## TLS Termination

**TLS is handled by the centralized nginx gateway** at `/Users/$(whoami)/nginx`. The CYOA game server exposes HTTP only on the internal Docker network (`stargate-shared`).

For direct HTTP access without TLS (e.g., debugging), the service optionally exposes port 8001 on localhost. See [NGINX-MIGRATION.md](NGINX-MIGRATION.md) for details.

---

## CYOA Game Server

The CYOA Game Server is a Django application that manages the game state, story generation, and difficulty system.

### Architecture

- **Server:** Django (Python) application managing game logic and prompting
- **Database:** SQLite for storing game turns, prompts, and judging statistics
- **Speech-to-Text:** Uses the local Whisper.cpp service via OpenAI-compatible API
- **LLM Router:** Supports multiple providers (Anthropic, OpenAI, OpenRouter, Ollama)

### Managing the Server

The server starts automatically with the docker stack, but you can manage it independently:

```bash
cd /Users/$(whoami)/llm-cyoa

# Build/Rebuild and start
docker compose -f docker-compose.mac.yml up -d --build cyoa-game-server

# Watch logs (essential for monitoring the game state)
docker compose -f docker-compose.mac.yml logs -f cyoa-game-server
```

### Load Prompts (First Run & Updates)

The system uses text files in `cyoa_prompts/` as the source of truth for Adventure, Judge, and Game Ending prompts.

To load or reload all prompts into the database:

```bash
# Using the convenience script
./reload-prompts.sh

# Or manually via Docker
docker exec -it cyoa-game-server python manage.py load_prompts
```

**Creating New Prompts:**
1. Create a new `.txt` file in `cyoa_prompts/` (e.g., `space-opera.txt`).
2. Run the reload command above.
3. It will automatically be imported as a new Adventure type.
4. Alternatively, you can create prompts directly in the Admin Database interface.

### Access the Admin Interface

- **URL:** https://cyoa.mac.stargate.lan/admin/

No account creation is required; you will be directed to the dashboard.

### Workshopping the Game Master Prompt

1. **Admin Tab:** Open the Admin interface in one browser tab. Navigate to the Prompts section to edit the active Judge or Adventure prompts.
2. **Game Tab:** Play the game in another tab.
3. **Logs:** Keep a terminal window open with `docker logs -f cyoa-game-server` to see the "thought process" of the LLM and the Judge's decisions in real-time.

Adjust the prompt text in the Admin interface, save, and the very next turn in the Game tab will use the updated logic.

