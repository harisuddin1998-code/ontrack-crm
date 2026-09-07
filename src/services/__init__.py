# src/services/__init__.py
"""
Services Package - Business Logic Layer
Export all services for easy importing
"""
from src.services.auth_service import AuthService
from src.services.po_service import POService
from src.services.vehicle_service import (
    VehicleMakeService, VehicleModelService, VehicleYearService,
    VehicleColorService, DeviceTypeService, CityService
)
from src.services.technician_service import (
    TechnicianService, TechnicianBikeService, TechnicianTripService,
    PetrolRateService, FuelReimbursementInvoiceService
)
from src.services.gps_service import GPSService
from src.services.email_service import EmailService
from src.services.notification_service import NotificationService
from src.services.payment_service import PaymentRecoveryService
from src.services.security_service import SecurityBriefingService
from src.services.redo_service import RedoService
from src.services.removal_service import RemovalService
from src.services.db_sync_service import DBSyncService
from src.services.report_service import ReportService
from src.services.pdf_service import PDFService
from src.services.non_reporting_service import NonReportingService
from src.services.fuel_rate_service import FuelRateService  # ✅ ADD THIS
from src.services.complaint_service import ComplaintService
from src.services.vehicle_search_service import VehicleSearchService

from src.services.user_service import UserService

__all__ = [
    'AuthService',
    'POService',
    'UserService',
    'VehicleMakeService',
    'VehicleModelService',
    'VehicleYearService',
    'VehicleColorService',
    'DeviceTypeService',
    'CityService',
    'TechnicianService',
    'TechnicianBikeService',
    'TechnicianTripService',
    'PetrolRateService',
    'FuelReimbursementInvoiceService',
    'GPSService',
    'EmailService',
    'NotificationService',
    'PaymentRecoveryService',
    'SecurityBriefingService',
    'RedoService',
    'RemovalService',
    'NonReportingService',
    'FuelRateService',  # ✅ ADD THIS
    'DBSyncService',
    'ReportService',
    'PDFService',
    'ComplaintService',
    'VehicleSearchService',
]