# src/forms/admin_forms.py
"""
Admin Management Forms
"""
from flask_wtf import FlaskForm
from wtforms import StringField, SelectField, SelectMultipleField, PasswordField, EmailField, FloatField, DateField
from wtforms.validators import DataRequired, Email, Length, Optional, NumberRange, ValidationError
from wtforms.widgets import ListWidget, CheckboxInput
from datetime import date

from src.services.user_service import UserService


class UserForm(FlaskForm):
    """User management form"""
    # Set by the edit route to this user's own id, so validate_username/
    # validate_email below don't flag the user's own unchanged
    # username/email as already taken by someone else.
    _user_id: int | None = None

    username = StringField('Username', validators=[DataRequired(), Length(min=3, max=80)])
    email = EmailField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[Optional(), Length(min=6)])
    text_case = SelectField('Username/Password Case', choices=[
        ('as_typed', 'As Typed'),
        ('lower', 'Force Lowercase'),
        ('upper', 'Force Uppercase'),
    ], default='as_typed', validators=[Optional()])
    role = SelectField('Role', choices=[
        ('sales', 'Sales'),
        ('installation', 'Installation'),
        ('admin', 'Admin'),
        ('manager', 'Manager'),
        ('security', 'Security Briefing'),
        ('payment_recovery', 'Installation Recovery Officer'),
        ('redo_technician', 'NR Team'),
        ('removal', 'Removal Technician'),
        ('complaint_manager', 'Complaint Manager'),
        ('recovery_officer', 'AMC / Annual Recovery Officer'),
        ('inventory', 'Inventory Manager'),
        ('device_recovery', 'Device Recovery (Power/Damage/Missing)'),
        ('suggestion_manager', 'Suggestions Manager'),
        ('executive', 'Executive')
    ], validators=[DataRequired()])
    additional_roles = SelectMultipleField('Additional Views', choices=[
        ('sales', 'Sales'),
        ('installation', 'Installation'),
        ('admin', 'Admin'),
        ('manager', 'Manager'),
        ('security', 'Security Briefing'),
        ('payment_recovery', 'Installation Recovery Officer'),
        ('redo_technician', 'NR Team'),
        ('removal', 'Removal Technician'),
        ('complaint_manager', 'Complaint Manager'),
        ('recovery_officer', 'AMC / Annual Recovery Officer'),
        ('inventory', 'Inventory Manager'),
        ('device_recovery', 'Device Recovery (Power/Damage/Missing)'),
        ('suggestion_manager', 'Suggestions Manager'),
        ('executive', 'Executive')
    ], option_widget=CheckboxInput(), widget=ListWidget(prefix_label=False), validators=[Optional()])
    name = StringField('Full Name', validators=[Optional(), Length(max=100)])
    contact = StringField('Contact Number', validators=[Optional(), Length(max=50)])
    is_active = SelectField('Status', choices=[
        ('True', 'Active'),
        ('False', 'Inactive')
    ], default='True')
    
    def validate_username(self, field):
        """Check if username already exists"""
        user_service = UserService()
        user = user_service.get_by_username(field.data)
        if user and (self._user_id is None or user.id != self._user_id):
            raise ValidationError('Username already exists')

    def validate_email(self, field):
        """Check if email already exists"""
        user_service = UserService()
        user = user_service.get_by_email(field.data)
        if user and (self._user_id is None or user.id != self._user_id):
            raise ValidationError('Email already exists')


class CityForm(FlaskForm):
    """City form"""
    name = StringField('City Name', validators=[DataRequired(), Length(max=100)])


class VehicleMakeForm(FlaskForm):
    """Vehicle make form"""
    name = StringField('Manufacturer Name', validators=[DataRequired(), Length(max=100)])


class VehicleModelForm(FlaskForm):
    """Vehicle model form"""
    name = StringField('Brand Name', validators=[DataRequired(), Length(max=100)])
    make_id = SelectField('Manufacturer', coerce=int, validators=[DataRequired()])


class VehicleYearForm(FlaskForm):
    """Vehicle year form"""
    year = StringField('Year / Model', validators=[DataRequired(), Length(min=4, max=4)])


class VehicleColorForm(FlaskForm):
    """Vehicle color form"""
    name = StringField('Color Name', validators=[DataRequired(), Length(max=50)])
    code = StringField('Color Code (Hex)', validators=[Optional(), Length(max=20)])


class DeviceTypeForm(FlaskForm):
    """Device type form"""
    name = StringField('Device Type', validators=[DataRequired(), Length(max=100)])


class PetrolRateForm(FlaskForm):
    """Petrol rate form"""
    rate_per_liter = FloatField('Rate per Liter (PKR)', validators=[
        DataRequired(),
        NumberRange(min=100, max=500, message='Rate must be between 100 and 500 PKR')
    ])
    effective_date = DateField('Effective Date', validators=[DataRequired()], default=date.today)