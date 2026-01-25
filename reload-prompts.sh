#!/bin/bash
# Script to reload adventure prompts with new pacing template variables
# Run this from the host machine to execute commands in the Docker container

echo "🔄 Reloading adventure prompts with pacing template support..."
echo ""

# Get the container name
CONTAINER=$(docker ps --filter "name=cyoa-game-server" --format "{{.Names}}" | head -n 1)

if [ -z "$CONTAINER" ]; then
    echo "❌ Error: Could not find running cyoa-game-server container"
    echo "   Please start the container with: docker-compose up -d"
    exit 1
fi

echo "📦 Using container: $CONTAINER"
echo ""

# Run migrations
echo "1️⃣  Running database migrations..."
docker exec -it "$CONTAINER" python manage.py migrate
echo ""

# Reload adventure prompts
echo "2️⃣  Reloading adventure prompts from disk..."
docker exec -it "$CONTAINER" python manage.py load_prompts
echo ""

echo "✅ Done! Your adventure prompts now support configurable turn pacing."
echo ""
echo "Next steps:"
echo "  1. Go to the admin interface at http://localhost:8001/admin/"
echo "  2. Edit your configuration to set turn count and phase pacing"
echo "  3. The prompts will automatically use your configured values"
echo ""
