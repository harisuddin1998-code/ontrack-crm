# src/services/vehicle_service.py
"""
Vehicle Service - Vehicle data management
"""
from typing import Optional, List, Dict, Any
from datetime import datetime

from src.models.vehicle import VehicleMake, VehicleModel, VehicleYear, VehicleColor, DeviceType, City
from src.repositories.base_repository import BaseRepository
from src.services.base_service import BaseService
from src.extensions import db
from src.utils.logging import get_logger

logger = get_logger(__name__)


class VehicleMakeService(BaseService[VehicleMake]):
    """Service for vehicle makes"""
    
    def __init__(self):
        super().__init__(BaseRepository(VehicleMake))
    
    def get_all_makes(self) -> List[VehicleMake]:
        """Get all makes sorted by name"""
        return self.repository.get_all(order_by='name')
    
    def get_make_by_name(self, name: str) -> Optional[VehicleMake]:
        """Get make by name"""
        return self.repository.get_by(name=name.upper().strip())
    
    def create_make(self, name: str) -> VehicleMake:
        """Create a new make"""
        name = name.upper().strip()
        if self.get_make_by_name(name):
            raise ValueError(f"Make '{name}' already exists")
        return self.repository.create(name=name)
    
    def update_make(self, make_id: int, name: str) -> Optional[VehicleMake]:
        """Update a make"""
        name = name.upper().strip()
        existing = self.get_make_by_name(name)
        if existing and existing.id != make_id:
            raise ValueError(f"Make '{name}' already exists")
        return self.repository.update(make_id, name=name)


class VehicleModelService(BaseService[VehicleModel]):
    """Service for vehicle models"""
    
    def __init__(self):
        super().__init__(BaseRepository(VehicleModel))
    
    def get_models_by_make(self, make_id: int) -> List[VehicleModel]:
        """Get models by make ID"""
        return self.repository.get_all(make_id=make_id)

    def get_make_model_map(self) -> Dict[str, List[str]]:
        """Model names grouped under their make's name.

        Purchase orders store make and model as names, not ids, so the map is
        keyed by name. It is handed to the PO forms whole and filtered in the
        browser: picking a make must narrow the model list immediately, and a
        round-trip per keystroke is not worth it for a list this size.

        A make with no models registered still gets an (empty) entry, so the
        form can say "no models on file" rather than silently showing all of
        them.
        """
        makes = {make.id: make.name for make in VehicleMake.query.all()}
        grouped: Dict[str, List[str]] = {name: [] for name in makes.values()}
        for model in VehicleModel.query.all():
            make_name = makes.get(model.make_id)
            if make_name and model.name:
                grouped[make_name].append(model.name)
        return {name: sorted(set(models)) for name, models in grouped.items()}
    
    def get_model_by_name(self, name: str, make_id: int) -> Optional[VehicleModel]:
        """Get model by name and make"""
        return self.repository.get_by(name=name.upper().strip(), make_id=make_id)
    
    def create_model(self, name: str, make_id: int) -> VehicleModel:
        """Create a new model"""
        name = name.upper().strip()
        if self.get_model_by_name(name, make_id):
            raise ValueError(f"Model '{name}' already exists for this make")
        return self.repository.create(name=name, make_id=make_id)
    
    def update_model(self, model_id: int, name: str, make_id: Optional[int] = None) -> Optional[VehicleModel]:
        """Update a model"""
        name = name.upper().strip()
        existing_model = self.repository.get_by_id(model_id)
        if existing_model:
            existing = self.get_model_by_name(name, make_id or existing_model.make_id)
            if existing and existing.id != model_id:
                raise ValueError(f"Model '{name}' already exists for this make")
        
        data = {'name': name}
        if make_id:
            data['make_id'] = make_id
        return self.repository.update(model_id, **data)


class VehicleYearService(BaseService[VehicleYear]):
    """Service for vehicle years"""
    
    def __init__(self):
        super().__init__(BaseRepository(VehicleYear))
    
    def get_all_years(self) -> List[VehicleYear]:
        """Get all years sorted descending"""
        return self.repository.get_all(order_by='year', desc=True)
    
    def get_year_by_value(self, year: str) -> Optional[VehicleYear]:
        """Get year by value"""
        return self.repository.get_by(year=year)
    
    def create_year(self, year: str) -> VehicleYear:
        """Create a new year"""
        if self.get_year_by_value(year):
            raise ValueError(f"Year '{year}' already exists")
        return self.repository.create(year=year)
    
    def get_year_choices(self) -> List[tuple]:
        """Get year choices for forms"""
        current_year = datetime.now().year
        return [(str(y), str(y)) for y in range(1900, current_year + 2)][::-1]


class VehicleColorService(BaseService[VehicleColor]):
    """Service for vehicle colors"""
    
    def __init__(self):
        super().__init__(BaseRepository(VehicleColor))
    
    def get_all_colors(self) -> List[VehicleColor]:
        """Get all colors sorted by name"""
        return self.repository.get_all(order_by='name')
    
    def get_color_by_name(self, name: str) -> Optional[VehicleColor]:
        """Get color by name"""
        return self.repository.get_by(name=name.upper().strip())
    
    def create_color(self, name: str, code: Optional[str] = None) -> VehicleColor:
        """Create a new color"""
        name = name.upper().strip()
        if self.get_color_by_name(name):
            raise ValueError(f"Color '{name}' already exists")
        return self.repository.create(name=name, code=code)
    
    def update_color(self, color_id: int, name: str, code: Optional[str] = None) -> Optional[VehicleColor]:
        """Update a color"""
        name = name.upper().strip()
        existing = self.get_color_by_name(name)
        if existing and existing.id != color_id:
            raise ValueError(f"Color '{name}' already exists")
        return self.repository.update(color_id, name=name, code=code)


class DeviceTypeService(BaseService[DeviceType]):
    """Service for device types"""
    
    def __init__(self):
        super().__init__(BaseRepository(DeviceType))
    
    def get_all_device_types(self) -> List[DeviceType]:
        """Get all device types sorted by name"""
        return self.repository.get_all(order_by='name')
    
    def get_device_by_name(self, name: str) -> Optional[DeviceType]:
        """Get device type by name"""
        return self.repository.get_by(name=name.upper().strip())
    
    def create_device_type(self, name: str) -> DeviceType:
        """Create a new device type"""
        name = name.upper().strip()
        if self.get_device_by_name(name):
            raise ValueError(f"Device type '{name}' already exists")
        return self.repository.create(name=name)
    
    def update_device_type(self, device_id: int, name: str) -> Optional[DeviceType]:
        """Update a device type"""
        name = name.upper().strip()
        existing = self.get_device_by_name(name)
        if existing and existing.id != device_id:
            raise ValueError(f"Device type '{name}' already exists")
        return self.repository.update(device_id, name=name)


class CityService(BaseService[City]):
    """Service for cities"""
    
    def __init__(self):
        super().__init__(BaseRepository(City))
    
    def get_all_cities(self) -> List[City]:
        """Get all cities sorted by name"""
        return self.repository.get_all(order_by='name')
    
    def get_city_by_name(self, name: str) -> Optional[City]:
        """Get city by name"""
        return self.repository.get_by(name=name.upper().strip())
    
    def create_city(self, name: str) -> City:
        """Create a new city"""
        name = name.upper().strip()
        if self.get_city_by_name(name):
            raise ValueError(f"City '{name}' already exists")
        return self.repository.create(name=name)
    
    def update_city(self, city_id: int, name: str) -> Optional[City]:
        """Update a city"""
        name = name.upper().strip()
        existing = self.get_city_by_name(name)
        if existing and existing.id != city_id:
            raise ValueError(f"City '{name}' already exists")
        return self.repository.update(city_id, name=name)