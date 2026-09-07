# src/scripts/seed_data.py
"""
Seed Database with Initial Data
"""
from datetime import date
from src.extensions import db
from src.models.user import User
from src.models.vehicle import City, VehicleMake, VehicleYear, VehicleColor, DeviceType
from src.models.technician import PetrolRate
from src.utils.logging import get_logger

logger = get_logger(__name__)


def seed_database():
    """Seed the database with initial data"""
    
    # Check if data already exists
    if User.query.count() > 0:
        logger.info("Database already has data. Skipping seed.")
        return
    
    print("Seeding database with initial data...")
    
    # Create default users
    users = [
        {'username': 'admin', 'email': 'admin@on-tracking.com', 'role': 'admin', 
         'name': 'Administrator', 'password': 'admin123', 'is_active': True},
        {'username': 'install', 'email': 'install@on-tracking.com', 'role': 'installation',
         'name': 'Installation Team', 'password': 'install123', 'is_active': True},
        {'username': 'sales1', 'email': 'sales1@on-tracking.com', 'role': 'sales',
         'name': 'Sales Person', 'contact': '03001234567', 'password': 'sales123', 'is_active': True},
        {'username': 'security', 'email': 'security@on-tracking.com', 'role': 'security',
         'name': 'Security Officer', 'contact': '03001234568', 'password': 'security123', 'is_active': True},
        {'username': 'payment', 'email': 'payment@on-tracking.com', 'role': 'payment_recovery',
         'name': 'Payment Recovery Officer', 'contact': '03001234569', 'password': 'payment123', 'is_active': True},
        {'username': 'redo', 'email': 'redo@on-tracking.com', 'role': 'redo_technician',
         'name': 'REDO Technician', 'contact': '03001234570', 'password': 'redo123', 'is_active': True},
        {'username': 'removal', 'email': 'removal@on-tracking.com', 'role': 'removal',
         'name': 'Removal Technician', 'contact': '03001234571', 'password': 'removal123', 'is_active': True},
    ]
    
    for user_data in users:
        password = user_data.pop('password')
        user = User(**user_data)
        user.set_password(password)
        db.session.add(user)
    
    db.session.commit()
    print(f"Created {len(users)} users")
    
    # Create default cities
    cities = ['KARACHI', 'LAHORE', 'ISLAMABAD', 'RAWALPINDI', 'FAISALABAD', 'MULTAN', 'PESHAWAR', 'QUETTA']
    for city_name in cities:
        city = City(name=city_name)
        db.session.add(city)
    db.session.commit()
    print(f"Created {len(cities)} cities")
    
    # Create default vehicle makes
    makes = ['TOYOTA', 'HONDA', 'SUZUKI', 'HYUNDAI', 'NISSAN', 'BMW', 'MERCEDES', 'AUDI', 'FORD', 'CHEVROLET']
    for make_name in makes:
        make = VehicleMake(name=make_name)
        db.session.add(make)
    db.session.commit()
    print(f"Created {len(makes)} vehicle makes")
    
    # Create default vehicle years (1900 to current year + 1)
    current_year = date.today().year
    for year in range(1900, current_year + 2):
        year_obj = VehicleYear(year=str(year))
        db.session.add(year_obj)
    db.session.commit()
    print(f"Created vehicle years from 1900 to {current_year + 1}")
    
    # Create default vehicle colors
    colors = ['BLACK', 'WHITE', 'SILVER', 'BLUE', 'RED', 'GREY', 'GREEN', 'YELLOW', 'ORANGE', 'PURPLE', 'BROWN', 'GOLD']
    for color_name in colors:
        color = VehicleColor(name=color_name)
        db.session.add(color)
    db.session.commit()
    print(f"Created {len(colors)} vehicle colors")
    
    # Create default device types
    devices = ['GPS TRACKER', 'FUEL SENSOR', 'TEMPERATURE SENSOR', 'DASH CAM', '4G TRACKER', '5G TRACKER']
    for device_name in devices:
        device = DeviceType(name=device_name)
        db.session.add(device)
    db.session.commit()
    print(f"Created {len(devices)} device types")
    
    # Create default petrol rate
    petrol_rate = PetrolRate(rate_per_liter=280.0, effective_date=date.today(), created_by=1)
    db.session.add(petrol_rate)
    db.session.commit()
    print("Created default petrol rate: PKR 280.00/liter")
    
    # Create sample Purchase Orders & Security Briefings
    from src.models.purchase_order import PurchaseOrder
    from src.models.security import SecurityBriefingData
    from src.models.payment import PaymentRecovery
    
    sample_pos = [
        {
            'po_number': 'PO-2026-0001',
            'activity_type': 'NEW_INSTALLATION',
            'owner_name': 'ALAM KHAN',
            'owner_contact': '03001234567',
            'contact_person_driver': 'DRIVER ALI',
            'reg_no': 'LEB-1234',
            'vehicle_make': 'TOYOTA',
            'vehicle_model': 'COROLLA',
            'vehicle_year': '2022',
            'vehicle_color': 'WHITE',
            'engine_number': 'ENG-998877',
            'chassis_number': 'CHS-112233',
            'sales_person_id': 3,
            'city': 'LAHORE',
            'vehicle_availability_location': 'GULBERG LAHORE',
            'scheduled_date': date.today(),
            'rates': 15000.0,
            'amc': 1200.0,
            'status': 'PENDING'
        },
        {
            'po_number': 'PO-2026-0002',
            'activity_type': 'NEW_INSTALLATION',
            'owner_name': 'MUHAMMAD TARIQ',
            'owner_contact': '03009876543',
            'contact_person_driver': 'SELF',
            'reg_no': 'KHI-9988',
            'vehicle_make': 'HONDA',
            'vehicle_model': 'CIVIC',
            'vehicle_year': '2023',
            'vehicle_color': 'BLACK',
            'engine_number': 'ENG-445566',
            'chassis_number': 'CHS-778899',
            'sales_person_id': 3,
            'city': 'KARACHI',
            'vehicle_availability_location': 'DHA KARACHI',
            'scheduled_date': date.today(),
            'rates': 20000.0,
            'amc': 1500.0,
            'status': 'COMPLETED'
        }
    ]
    
    for po_data in sample_pos:
        po = PurchaseOrder(**po_data)
        db.session.add(po)
        db.session.flush()
        
        # Create SecurityBriefingData for each PO
        briefing = SecurityBriefingData(
            po_id=po.id,
            segment='PRIVATE',
            cnic='35202-1234567-1',
            address='HOUSE 123 STREET 4',
            father_name='FATHER NAME',
            mother_name='MOTHER NAME',
            status='PENDING' if po.status == 'PENDING' else 'COMPLETED'
        )
        db.session.add(briefing)
        
        # Create PaymentRecovery for each PO
        payment = PaymentRecovery(
            po_id=po.id,
            total_rates=po.rates,
            total_amc=po.amc,
            total_amount=po.rates + po.amc,
            amount_received=po.rates + po.amc if po.status == 'COMPLETED' else 0.0,
            remaining_amount=0.0 if po.status == 'COMPLETED' else po.rates + po.amc,
            payment_status='PAID' if po.status == 'COMPLETED' else 'PENDING'
        )
        db.session.add(payment)
        
    db.session.commit()
    print("Created sample purchase orders, security briefings, and payment recovery records.")

    print("\nDatabase seeded successfully!")
    print("\nDefault Login Credentials:")
    print("   Admin:      admin / admin123")
    print("   Installation: install / install123")
    print("   Sales:      sales1 / sales123")
    print("   Security:   security / security123")
    print("   Payment Recovery: payment / payment123")
    print("   REDO Technician: redo / redo123")
    print("   Removal Technician: removal / removal123")