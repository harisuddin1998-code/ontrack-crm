# src/models/__init__.py
"""
Models Package - Database models
Export all models for easy importing
"""
from src.models.user import User
from src.models.purchase_order import PurchaseOrder
from src.models.vehicle import VehicleMake, VehicleModel, VehicleYear, VehicleColor, DeviceType, City
from src.models.technician import (
    Technician, TechnicianBike, TechnicianTrip, PetrolRate,
    FuelReimbursementInvoice, FuelInvoiceExpense
)
from src.models.security import SecurityBriefingData
from src.models.payment import PaymentRecovery, PaymentHistory
from src.models.gps import CurrentLocation, NonReportingVehicle, NonReportingConversation
from src.models.activity import ActivityLog
from src.models.redo import RedoActivity
from src.models.removal import RemovalTransferActivity, RemovalRetainedActivity, VehicleFlag
from src.models.annual_recovery import (
    AnnualRecoveryClient,
    AnnualRecoveryVehicle,
    AnnualRecoveryFollowup,
    AnnualRecoveryHistory,
    AnnualRecoveryAuditLog
)
from src.models.complaint import Complaint
from src.models.inventory import InventoryDevice, InventoryStockItem, TechnicianStockIssuance
from src.models.corporate import CorporateVehicle
from src.models.live_amc import LiveAmcAssignment
from src.models.amc_recovery_record import AmcRecoveryRecord
from src.models.amc_database_assignment import AmcDatabaseAssignment
from src.models.installation_recovery import InstallationRecoveryCharge, InstallationRecoveryFollowup
from src.models.notification import UserNotification
from src.models.report_recipient import ReportRecipient
from src.models.suggestion import Suggestion, SuggestionMessage
from src.models.amc_invoice import AmcInvoice
from src.models.vehicle_registry import VehicleRegistryEntry

__all__ = [
    'User',
    'PurchaseOrder',
    'VehicleMake',
    'VehicleModel',
    'VehicleYear',
    'VehicleColor',
    'DeviceType',
    'City',
    'Technician',
    'TechnicianBike',
    'TechnicianTrip',
    'PetrolRate',
    'FuelReimbursementInvoice',
    'FuelInvoiceExpense',
    'SecurityBriefingData',
    'PaymentRecovery',
    'PaymentHistory',
    'CurrentLocation',
    'NonReportingVehicle',
    'NonReportingConversation',
    'ActivityLog',
    'RedoActivity',
    'RemovalTransferActivity',
    'RemovalRetainedActivity',
    'VehicleFlag',
    'AnnualRecoveryClient',
    'AnnualRecoveryVehicle',
    'AnnualRecoveryFollowup',
    'AnnualRecoveryHistory',
    'AnnualRecoveryAuditLog',
    'Complaint',
    'InventoryDevice',
    'InventoryStockItem',
    'TechnicianStockIssuance',
    'CorporateVehicle',
    'LiveAmcAssignment',
    'AmcRecoveryRecord',
    'AmcDatabaseAssignment',
    'InstallationRecoveryCharge',
    'InstallationRecoveryFollowup',
    'UserNotification',
    'ReportRecipient',
    'AmcInvoice',
    'VehicleRegistryEntry',
    'Suggestion',
    'SuggestionMessage',
]