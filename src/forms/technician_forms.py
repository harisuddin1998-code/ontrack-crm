# src/forms/technician_forms.py
"""
Technician Management Forms
"""
from flask_wtf import FlaskForm
from wtforms import StringField, SelectField, FloatField, BooleanField, TextAreaField
from wtforms.validators import DataRequired, Optional, Length, NumberRange, ValidationError

# Import from technician_service
from src.services.technician_service import TechnicianBikeService


class TechnicianForm(FlaskForm):
    """Form for creating and editing technicians"""
    name = StringField('Technician Name', validators=[DataRequired(), Length(max=100)])
    contact = StringField('Contact Number', validators=[Optional(), Length(max=20)])
    address = TextAreaField('Home Address (Point A)', validators=[Optional()])
    home_lat = StringField('Home Latitude', validators=[Optional()])
    home_lng = StringField('Home Longitude', validators=[Optional()])
    is_active = SelectField('Status', choices=[('True', 'Active'), ('False', 'Inactive')], default='True')
    
    # GPS Sync Fields
    sync_gps = BooleanField('Sync GPS Location', default=False)
    imei_for_sync = StringField('Tracker IMEI (for GPS sync)', validators=[Optional(), Length(max=50)])

    # Bike Assignment Fields (Unified Form)
    bike_registration = StringField('Bike Registration No', validators=[Optional(), Length(max=50)])
    imei = StringField('Tracker IMEI Number', validators=[Optional(), Length(min=10, max=50)])
    bike_model = StringField('Bike Model', validators=[Optional(), Length(max=100)])
    fuel_efficiency = FloatField('Fuel Efficiency (km/liter)', validators=[
        Optional(),
        NumberRange(min=10, max=100)
    ], default=35.0)
    bike_active = SelectField('Bike Status', choices=[('True', 'Active'), ('False', 'Inactive')], default='True')


class TechnicianBikeForm(FlaskForm):
    """Technician bike assignment form"""
    technician_id = SelectField('Technician', coerce=int, validators=[DataRequired()])
    imei = StringField('Tracker IMEI Number', validators=[DataRequired(), Length(min=10, max=50)])
    bike_registration = StringField('Bike Registration No', validators=[DataRequired(), Length(max=50)])
    bike_model = StringField('Bike Model', validators=[Optional(), Length(max=100)])
    fuel_efficiency = FloatField('Fuel Efficiency (km/liter)', validators=[
        Optional(),
        NumberRange(min=10, max=100)
    ], default=35.0)
    is_active = SelectField('Status', choices=[
        ('True', 'Active'),
        ('False', 'Inactive')
    ], default='True')
    
    def __init__(self, *args, **kwargs):
        """Initialize the form"""
        super(TechnicianBikeForm, self).__init__(*args, **kwargs)
        self._obj = None
    
    def validate_technician_id(self, field):
        """Check if technician already has a bike (skip if editing)"""
        # Check if we're editing (has instance id)
        if self._obj and self._obj.id:
            # If editing, check if the technician is the same as the current one
            if self._obj.technician_id == field.data:
                return  # Skip validation for same technician (editing)
        
        # Check if technician already has a bike
        try:
            bike_service = TechnicianBikeService()
            bike = bike_service.get_bike_by_technician(field.data)
            if bike:
                # If editing, allow if it's the same bike
                if self._obj and self._obj.id == bike.id:
                    return
                raise ValidationError('This technician already has a bike assigned')
        except Exception:
            # If service not available, skip validation (will be caught by database constraint)
            pass
    
    def validate_imei(self, field):
        """Check if IMEI already assigned (skip if editing)"""
        try:
            bike_service = TechnicianBikeService()
            bike = bike_service.get_bike_by_imei(field.data)
            if bike:
                # If editing, allow if it's the same bike
                if self._obj and self._obj.id == bike.id:
                    return
                raise ValidationError('This IMEI is already assigned to another bike')
        except Exception:
            # If service not available, skip validation
            pass
    
    def set_obj(self, obj):
        """Set the object for edit mode"""
        self._obj = obj