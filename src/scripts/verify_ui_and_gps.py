import os
import sys

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from src.app import create_app
from src.services.gps_service import GPSService

def verify():
    app = create_app('development')
    app.config['TESTING'] = True
    app.config['LOGIN_DISABLED'] = True
    
    with app.test_client() as client:
        # 1. Test Annual Recovery Dashboard Route
        res = client.get('/annual-recovery/')
        print(f"Annual Recovery Dashboard HTTP Status: {res.status_code}")
        assert res.status_code == 200, "Dashboard route failed"
        
        # 2. Test Annual Recovery Stats API
        res_stats = client.get('/annual-recovery/api/stats')
        print(f"Annual Recovery Stats HTTP Status: {res_stats.status_code}")
        print(f"Stats Data: {res_stats.get_json()}")
        assert res_stats.status_code == 200, "Stats API failed"
        
        # 3. Test Annual Recovery Clients API
        res_clients = client.get('/annual-recovery/api/clients')
        print(f"Annual Recovery Clients HTTP Status: {res_clients.status_code}")
        client_count = len(res_clients.get_json())
        print(f"Total Clients Returned: {client_count}")
        assert res_clients.status_code == 200, "Clients API failed"

    with app.app_context():
        # 4. Test GPS Service test_imei and sync without unicode encoding crash
        gps_service = GPSService()
        imei_res = gps_service.test_imei('862292056620214')
        print(f"GPS Test IMEI Result: {imei_res}")
        assert 'imei' in imei_res, "GPS test IMEI failed"
        
    print("\nALL VERIFICATIONS PASSED SUCCESSFULLY!")

if __name__ == '__main__':
    verify()
