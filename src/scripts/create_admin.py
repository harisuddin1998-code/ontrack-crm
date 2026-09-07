# src/scripts/create_admin.py
"""
Create Admin User Script
"""
from src.extensions import db
from src.models.user import User
from src.app import create_app


def create_admin():
    """Create an admin user"""
    app = create_app()
    
    with app.app_context():
        # Check if admin exists
        existing_admin = User.query.filter_by(role='admin').first()
        if existing_admin:
            print(f"Admin user already exists: {existing_admin.username}")
            return
        
        # Create admin
        admin = User(
            username='admin',
            email='admin@on-tracking.com',
            role='admin',
            name='Administrator',
            is_active=True
        )
        admin.set_password('admin123')
        db.session.add(admin)
        db.session.commit()
        
        print("Admin user created successfully!")
        print("Username: admin")
        print("Password: admin123")


if __name__ == "__main__":
    create_admin()