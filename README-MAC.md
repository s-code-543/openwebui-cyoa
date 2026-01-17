# openwebui-cyoa - macOS Setup Guide

This guide documents the macOS (Apple Silicon) setup for components that have been tested and verified working.

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

## Open Web UI Setup

### 1. Create SSL Certificates

Generate self-signed certificates for HTTPS access (required for mobile):

```bash
cd /Users/$(whoami)/openwebui-cyoa
mkdir -p ssl

openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout ssl/openwebui.key \
  -out ssl/openwebui.crt \
  -subj "/C=US/ST=State/L=City/O=Stargate/CN=mac.stargate.lan" \
  -addext "subjectAltName=DNS:mac.stargate.lan,DNS:*.stargate.lan,DNS:localhost,IP:127.0.0.1"
```

**Note:** Replace `mac.stargate.lan` with your actual local hostname if different.

### 2. Set Environment Variables

Create a `.env` file with your API keys:

```bash
cd /Users/$(whoami)/openwebui-cyoa
cat <<EOF > .env
ANTHROPIC_API_KEY=sk-ant-your-key-here
EOF
```

### 3. Start the Containers

Ensure Docker Desktop is running, then start the stack:

```bash
cd /Users/$(whoami)/openwebui-cyoa

# Start the containers (detached mode)
docker compose -f docker-compose.mac.yml up -d

# Or to watch logs (foreground)
docker compose -f docker-compose.mac.yml up
```

### 4. Access Open Web UI

- **URL:** https://openwebui.mac.stargate.lan (or your configured local hostname)

Accept the self-signed certificate warning in your browser.

### 5. Verify Services

In Open Web UI, Ollama models should appear automatically. Whisper STT should work when you use the microphone button.

### 6. Configure Audio Settings (Important!)

To prevent the microphone from cutting you off after short pauses:

1. Go to **Settings → Audio** (user settings, not admin settings)
2. Find **"Speech Auto-Send"** toggle
3. **Turn it ON**, then click **Save**
4. **Turn it OFF**, then click **Save** again

This toggle dance is required due to a UI quirk - it ensures the setting is properly applied and the recorder waits for you to manually stop instead of auto-detecting silence.

---

## CYOA Game Server Setup

The CYOA Game Server is a standalone backend application that manages the game state, story generation, and difficulty system. It is **no longer** just an Open Web UI proxy.

### Architecture

- **Server:** Django (Python) application managing game logic and prompting.
- **Database:** SQLite for storing game turns, prompts, and judging statistics.
- **Speech-to-Text:** Configured to use the local Whisper.cpp service via speaches/openai-compatible API.

### 1. Start the Server

The server starts automatically with the docker stack, but you can manage it independently:

```bash
cd /Users/$(whoami)/openwebui-cyoa

# Build/Rebuild and start
docker compose -f docker-compose.mac.yml up -d --build cyoa-game-server

# Watch logs (essential for monitoring the game state)
docker compose -f docker-compose.mac.yml logs -f cyoa-game-server
```

### 2. Load Prompts (First Run & Updates)

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

### 3. Access the Admin Interface

- **URL:** https://cyoa.mac.stargate.lan/admin/

No account creation is required; you will be directed to the dashboard.

### 4. Workshopping the Game Master Prompt

1. **Admin Tab:** Open the Admin interface in one browser tab. Navigate to the Prompts section to edit the active Judge or Adventure prompts.
2. **Game Tab:** Play the game in another tab.
3. **Logs:** Keep a terminal window open with `docker logs -f cyoa-game-server` to see the "thought process" of the LLM and the Judge's decisions in real-time.

Adjust the prompt text in the Admin interface, save, and the very next turn in the Game tab will use the updated logic.

