# src/scripts/init_db.py
"""
Database Initialization Script
"""
from src.extensions import db
from src.app import create_app

# Import ALL models before creating tables
from src.models import (
    User, PurchaseOrder, VehicleMake, VehicleModel, VehicleYear,
    VehicleColor, DeviceType, City, Technician, TechnicianBike,
    TechnicianTrip, PetrolRate, FuelReimbursementInvoice,
    SecurityBriefingData, PaymentRecovery, PaymentHistory,
    CurrentLocation, NonReportingVehicle, NonReportingConversation,
    ActivityLog, RedoActivity, RemovalTransferActivity, RemovalRetainedActivity
)


def init_database():
    """Initialize the database with all tables"""
    app = create_app()
    
    with app.app_context():
        # Get the database URI from config
        db_uri = app.config.get('SQLALCHEMY_DATABASE_URI')
        print(f"Using database URI: {db_uri}")
        
        print("Creating database tables...")
        db.create_all()
        print("Database tables created successfully!")
        
        # Verify tables were created
        from sqlalchemy import inspect
        inspector = inspect(db.engine)
        tables = inspector.get_table_names()
        print(f"Tables created: {tables}")
        
        # Seed data
        from src.scripts.seed_data import seed_database
        seed_database()


if __name__ == "__main__":
    init_database()