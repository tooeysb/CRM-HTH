#!/bin/bash
# Email Processing Desktop Widget Launcher

cd "$(dirname "$0")"

# Kill any existing widget server
pkill -f widget_server.py 2>/dev/null
sleep 1

echo "🚀 Starting Email Processing Widget..."
echo "📊 Opening widget as standalone app..."
echo ""

# Start server in background
python3 widget_server.py &
SERVER_PID=$!

# Wait for server to start
sleep 2

# Get screen resolution to position in top-right corner
SCREEN_WIDTH=$(system_profiler SPDisplaysDataType | grep Resolution | awk '{print $2}' | head -1)
if [ -z "$SCREEN_WIDTH" ]; then
    SCREEN_WIDTH=1920  # Default if can't detect
fi

# Simple fixed size - 200px content + 32px chrome
X_POS=$((SCREEN_WIDTH - 252))
Y_POS=60

# Open in Chrome as standalone app
if [ -f "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" ]; then
    /Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
      --app="http://localhost:8765/widget" \
      --window-size=232,300 \
      --window-position=$X_POS,$Y_POS \
      > /dev/null 2>&1 &

    echo "✅ Widget opened in Chrome app mode"
elif [ -f "/Applications/Safari.app/Contents/MacOS/Safari" ]; then
    # Fallback to Safari (opens in tab, but user can make it standalone)
    open -a Safari "http://localhost:8765/widget"
    echo "✅ Widget opened in Safari"
    echo "💡 Tip: Use Safari → File → 'Add to Dock' to make it standalone"
else
    # Fallback to default browser
    open "http://localhost:8765/widget"
    echo "✅ Widget opened in default browser"
fi

echo ""
echo "📌 Widget is now on your desktop!"
echo "🔄 Auto-refreshes every 10 seconds"
echo "❌ Press Ctrl+C to stop the server"
echo ""

# Wait for user to stop
wait $SERVER_PID
