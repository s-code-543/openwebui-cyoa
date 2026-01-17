# openwebui-cyoa - macOS Setup Guide

This guide documents the macOS (Apple Silicon) setup for components that have been tested and verified working.

---

## Prerequisites

- macOS with Apple Silicon (M1/M2/M3)
- [Homebrew](https://brew.sh) installed
- **Xcode** from the App Store - Required for Core ML model generation
  - After installing, open Xcode and accept the license agreement
  - Or run: `sudo xcodebuild -license accept`
- **Colima** for Docker (lighter than Docker Desktop)
  ```bash
  brew install colima docker docker-compose
  colima start
  
  # Add Colima socket to shell profile (permanent)
  echo 'export DOCKER_HOST="unix://${HOME}/.colima/default/docker.sock"' >> ~/.zshrc
  source ~/.zshrc
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

Make sure Colima is running, then start the stack:

```bash
# Ensure Colima is running
colima status || colima start

# Start the containers (detached mode)
cd /Users/$(whoami)/openwebui-cyoa
docker compose -f docker-compose.mac.yml up -d

# Or to watch logs (foreground)
docker compose -f docker-compose.mac.yml up
```

### 4. Access Open Web UI

- **HTTPS (recommended):** https://mac.stargate.lan or https://localhost
- **HTTP (fallback):** http://localhost:3000

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

The CYOA Game Server provides a dual-LLM architecture for Choose Your Own Adventure games. It acts as an OpenAI-compatible proxy that:
1. Routes requests to your storyteller LLM (any Ollama model or Claude)
2. Passes the output through a judge LLM to ensure fair game design
3. Logs all corrections for prompt tuning

### Architecture

- **Storyteller LLM:** Generates the story turns (configurable: Ollama or Claude)
- **Judge LLM:** Validates story turns don't break game design rules
- **Admin Interface:** Edit judge prompts and view correction statistics

### 1. Start the CYOA Game Server

The server is already configured in `docker-compose.mac.yml`:

```bash
cd /Users/$(whoami)/openwebui-cyoa

# Build and start the game server
docker compose -f docker-compose.mac.yml up -d cyoa-game-server

# Watch the logs
docker compose -f docker-compose.mac.yml logs -f cyoa-game-server
```

### 2. Initialize the Database

Run migrations and load prompts:

```bash
# Run database migrations
docker compose -f docker-compose.mac.yml exec cyoa-game-server python manage.py migrate

# Load the judge prompt and adventure stories
docker compose -f docker-compose.mac.yml exec cyoa-game-server python manage.py load_initial_prompts
docker compose -f docker-compose.mac.yml exec cyoa-game-server python manage.py load_story_prompts

# Create an admin user (you'll be prompted for password)
docker compose -f docker-compose.mac.yml exec cyoa-game-server python manage.py createsuperuser --username admin --email admin@example.com
```

### 3. Access the Admin Interface

Open http://localhost:8001/admin/login/ and log in with your admin credentials.

You can:
- **Dashboard:** View correction statistics
- **Audit Log:** See all requests and which ones were modified by the judge
- **Prompts:** Edit judge prompt versions and set which one is active

The initial judge prompt is loaded as version 1 and set as active by default.

### 4. Install Session ID Injector Function

1. Open Open Web UI: https://localhost
2. Go to **Admin Panel → Functions**
3. Click **+ Add Function** (top right)
4. Copy the contents of `openwebui_functions/input_functions/cyoa-session-id-injector.py`
5. Paste into the function editor
6. Name it **game-id**
7. Click **Save**
8. Go to **Workspace → Models**
9. For each CYOA model (`cyoa-base`, `cyoa-moderated`, `gameserver-cyoa`):
   - Click the model's settings icon
   - Under **Functions**, enable **game-id** (toggle to Available)
   - Under **Default Functions**, add **game-id**
   - Click **Save**

### 5. Configure Open Web UI to Use CYOA Server

1. Go to **Admin Panel → Settings → Connections**
2. Add a new **OpenAI API** connection:
   - **API Base URL:** `http://cyoa-game-server:8000/v1`
   - **API Key:** (leave blank)
   - **Enable:** ✓

### 6. Workshopping the game master prompt

1. Open the admin interface in one tab: http://localhost:8001/admin/login/
2. Start a new chat in Open Web UI
3. Add **both** `gameserver-cyoa-base` and `gameserver-cyoa-moderated` models to the same chat for side-by-side comparison
4. Provide your game scenario and watch the unmoderated output vs the judge-corrected output
5. Tune the judge prompt in the admin interface based on what you see

---

