#!/bin/bash
# Setup script for CYOA Game Server

set -e

echo "🎲 CYOA Game Server Setup"
echo "=========================="
echo ""

# Check if running from correct directory
if [ ! -f "manage.py" ]; then
    echo "❌ Error: Must run from cyoa-game-server directory"
    exit 1
fi

echo "📦 Creating database directory..."
mkdir -p db

echo "🗄️  Running migrations..."
python manage.py makemigrations
python manage.py migrate

echo "👤 Creating superuser..."
echo "You'll be prompted to create an admin account:"
python manage.py createsuperuser

echo "📝 Loading prompts..."
python manage.py load_prompts

echo ""
echo "✅ Setup complete!"
echo ""
echo "To start the server:"
echo "  python manage.py runserver 0.0.0.0:8000"
echo ""
echo "Or use docker-compose from the parent directory:"
echo "  docker-compose -f docker-compose.mac.yml up -d cyoa-game-server"
echo ""
echo "Admin interface will be available at:"
echo "  http://localhost:8001/admin/login/"
echo ""
