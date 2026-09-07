# src/forms/po_forms.py
"""
PO Forms - Purchase Order creation and management
"""
from flask_wtf import FlaskForm
from wtforms import StringField, SelectField, DateField, FloatField, TextAreaField, IntegerField
from wtforms.validators import DataRequired, Optional, Length, NumberRange
from datetime import date


def coerce_int_or_empty(val):
    if val is None or val == '' or val == 'None':
        return ''
    try:
        return int(val)
    except (ValueError, TypeError):
        return ''


# Transmission is a fixed list, not a free text box. SJ_MIS's own column is
# free text and shows what that costs: 806 vehicles say "1234" and 194 say
# "NLL", and no report can tell those from a real answer.
TRANSMISSION_CHOICES = [
    ('', 'Select Transmission'),
    ('AUTOMATIC', 'Automatic'),
    ('MANUAL', 'Manual'),
    ('CVT', 'CVT'),
    ('HYBRID', 'Hybrid'),
    ('OTHER', 'Other'),
]


class POCreationForm(FlaskForm):
    """Simplified Form for creating POs. Also reused (with the extra
    optional fields below) as the comprehensive Admin PO edit form -
    unrendered fields on the plain creation template are simply not
    submitted, so this stays safe for both flows."""
    owner_name = StringField('Customer Name', validators=[DataRequired(), Length(max=100)])
    owner_contact = StringField('Contact Number', validators=[DataRequired(), Length(max=20)])
    contact_person_driver = StringField('Driver Contact', validators=[Optional(), Length(max=20)])
    reg_no = StringField('Registration Number', validators=[DataRequired(), Length(max=20)])
    vehicle_make = SelectField('Manufacturer', choices=[], validators=[DataRequired()])
    vehicle_model = SelectField('Brand', choices=[], validators=[DataRequired()])
    sales_person_id = SelectField('Sales Person', coerce=coerce_int_or_empty, validators=[DataRequired()])
    vehicle_availability_location = StringField('Vehicle / Installation Location', validators=[DataRequired(), Length(max=200)])
    existing_customer_name = StringField('Existing Customer Name', validators=[Optional(), Length(max=200)])
    existing_vehicle_number = StringField('Existing Vehicle Number', validators=[Optional(), Length(max=100)])
    rates = FloatField('Rates', validators=[Optional()], default=0.0)
    amc = FloatField('AMC', validators=[Optional()], default=0.0)

    # Admin-edit-only fields (not shown on the plain PO creation form) -
    # give administration full visibility/edit rights over every PO field.
    vehicle_year = SelectField('Year / Model', choices=[], validators=[Optional()])
    vehicle_color = SelectField('Color', choices=[], validators=[Optional()])
    engine_number = StringField('Engine Number', validators=[Optional(), Length(max=100)])
    chassis_number = StringField('Chassis Number', validators=[Optional(), Length(max=100)])
    city = SelectField('City', choices=[], validators=[Optional()])
    scheduled_date = DateField('Scheduled Date', validators=[Optional()])
    technician_assigned = StringField('Technician Assigned', validators=[Optional(), Length(max=100)])
    imei_no = StringField('Device IMEI', validators=[Optional(), Length(max=50)])
    sim_no = StringField('SIM Number', validators=[Optional(), Length(max=50)])
    device_type = StringField('Device Type', validators=[Optional(), Length(max=50)])
    device_location = StringField('Device Location', validators=[Optional(), Length(max=200)])
    fuel = StringField('Fuel (PKR)', validators=[Optional(), Length(max=50)])
    tested_by = StringField('Tested By', validators=[Optional(), Length(max=100)])
    arranged_by_sales_person = StringField('Arranged By', validators=[Optional(), Length(max=100)])
    remarks = TextAreaField('Remarks', validators=[Optional()])
    status = SelectField('Status', choices=[
        ('PENDING', 'Pending'),
        ('IN_PROGRESS', 'In Progress'),
        ('COMPLETED', 'Completed'),
        ('CANCELLED', 'Cancelled'),
    ], validators=[Optional()])


class InstallationUpdateForm(FlaskForm):
    """Form for updating installation details.

    Two audiences, one form. The installation team fills in the technical
    fields below - what was fitted, by whom, and where. The order's own
    particulars (who the customer is, which vehicle, what it is worth) are
    the Administrator's alone: they are what the order *is*, not what was
    done to it, and an installer correcting a customer's name in the field
    silently rewrites the record Sales raised.

    The administrator-only fields are declared here but rendered and read
    only for an admin (see `installation.update_po` and its template), so an
    installer's browser never carries them and a hand-made POST cannot bring
    them back - an unrendered field is simply not submitted, and the route
    drops it regardless.
    """
    # --- Administrator only -------------------------------------------
    owner_name = StringField('Customer Name', validators=[Optional(), Length(max=200)])
    owner_contact = StringField('Contact Number', validators=[Optional(), Length(max=50)])
    contact_person_driver = StringField('Driver Contact', validators=[Optional(), Length(max=200)])
    reg_no = StringField('Registration Number', validators=[Optional(), Length(max=50)])
    sales_person_id = SelectField('Sales Person', coerce=coerce_int_or_empty,
                                  choices=[], validators=[Optional()])
    existing_customer_name = StringField('Existing Customer Name',
                                         validators=[Optional(), Length(max=200)])
    existing_vehicle_number = StringField('Existing Vehicle Number',
                                          validators=[Optional(), Length(max=100)])
    rates = FloatField('Rates', validators=[Optional()])
    amc = FloatField('AMC', validators=[Optional()])
    tested_by = StringField('Tested By', validators=[Optional(), Length(max=100)])

    # --- Installation team --------------------------------------------
    # Transferred Vehicle & Location Details
    # Manufacturer, Brand, Year / Model, Color - the order a vehicle is
    # described in - then the two the source system barely holds and the
    # installer is best placed to record.
    vehicle_make = SelectField('Manufacturer', choices=[], validators=[Optional()])
    vehicle_model = SelectField('Brand', choices=[], validators=[Optional()])
    vehicle_year = SelectField('Year / Model', choices=[], validators=[Optional()])
    vehicle_color = SelectField('Color', choices=[], validators=[Optional()])
    transmission = SelectField('Transmission', choices=TRANSMISSION_CHOICES,
                               validators=[Optional()])
    power_cc = StringField('Power CC', validators=[Optional(), Length(max=20)])
    engine_number = StringField('Engine Number', validators=[Optional(), Length(max=50)])
    chassis_number = StringField('Chassis Number', validators=[Optional(), Length(max=50)])
    city = SelectField('City', choices=[], validators=[Optional()])
    vehicle_availability_location = StringField('Vehicle / Installation Location', validators=[Optional(), Length(max=200)])
    scheduled_date = DateField('Scheduled Date', validators=[Optional()], format='%Y-%m-%d')
    
    # Installation Technical Details
    technician_assigned = SelectField('Technician Assigned', coerce=str, validators=[Optional()])
    imei_no = StringField('Device IMEI', validators=[Optional(), Length(max=50)])
    sim_no = StringField('SIM Number', validators=[Optional(), Length(max=50)])
    device_type = SelectField('Device Type', choices=[], validators=[Optional()])
    device_location = StringField('Device Location', validators=[Optional(), Length(max=200)])
    sim_network = SelectField('SIM Network', choices=[
        ('', 'Select SIM Network'),
        ('MOBILINK', 'MOBILINK'),
        ('ZONG', 'ZONG'),
        ('WARID', 'WARID'),
        ('UFONE', 'UFONE'),
        ('TELENOR', 'TELENOR')
    ], validators=[Optional()])
    accessories_installed = StringField('Accessories Installed', validators=[Optional(), Length(max=500)])
    fuel = StringField('Fuel (PKR)', validators=[Optional(), Length(max=50)])
    arranged_by_sales_person = StringField('Arranged By', validators=[Optional(), Length(max=100)])
    remarks = TextAreaField('Remarks', validators=[Optional()])
    status = SelectField('Status', choices=[
        ('PENDING', 'Pending'),
        ('IN_PROGRESS', 'In Progress'),
        ('COMPLETED', 'Completed')
    ], validators=[DataRequired()])
    
    def __init__(self, *args, **kwargs):
        super(InstallationUpdateForm, self).__init__(*args, **kwargs)
        # Choices will be populated dynamically in the route
        self.technician_assigned.choices = [('', 'Select Technician')]
        self.device_type.choices = [('', 'Select Device Type')]