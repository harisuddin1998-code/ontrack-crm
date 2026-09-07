# run.py
"""
Local & Network Hosting Runner for ON TRACK CRM
Allows the app to run locally and be accessed by others on the same network (LAN/Wi-Fi).
"""
import os
import sys
import socket

# Ensure project root directory is in sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.app import create_app
from src.extensions import db, socketio

app = create_app('development')

def get_local_ip():
    """Get local IP address of this computer on the LAN/Wi-Fi"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        
    local_ip = get_local_ip()
    
    print("=" * 65)
    print("🚀 ON TRACK CRM SERVER READY FOR LOCAL & NETWORK HOSTING")
    print("=" * 65)
    print(f"💻 On THIS computer:  http://127.0.0.1:5000  or  http://localhost:5000")
    print(f"🌐 For OTHER PEOPLE:   http://{local_ip}:5000")
    print("=" * 65)
    print("💡 Note: For other people to access it, ensure they are on the same Wi-Fi/LAN")
    print("   and Windows Firewall allows Python/Port 5000 incoming connections.")
    print("=" * 65)
    
    socketio.run(app, host='0.0.0.0', port=5000, debug=True, allow_unsafe_werkzeug=True)
