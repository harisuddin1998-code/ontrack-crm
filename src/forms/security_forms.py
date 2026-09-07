# src/forms/security_forms.py
"""
Security Briefing Forms
"""
from flask_wtf import FlaskForm
from wtforms import StringField, DateField, SelectField, TextAreaField, BooleanField
from wtforms.validators import DataRequired, Optional, Length


class SecurityBriefingForm(FlaskForm):
    """Security briefing form"""
    # Basic Information (Read-Only from PO/SSOT, made Optional in validation)
    registration_no = StringField('Registration No', validators=[Optional(), Length(max=50)])
    engine_no = StringField('Engine No', validators=[Optional(), Length(max=100)])
    chassis_no = StringField('Chassis No', validators=[Optional(), Length(max=100)])
    make = StringField('Make', validators=[Optional(), Length(max=50)])
    model = StringField('Model', validators=[Optional(), Length(max=50)])
    year = StringField('Year', validators=[Optional(), Length(max=4)])
    color = StringField('Color', validators=[Optional(), Length(max=20)])
    
    # Customer Information (Read-Only from PO)
    customer_name = StringField('Customer Name', validators=[Optional(), Length(max=200)])
    phone = StringField('Phone', validators=[Optional(), Length(max=50)])
    cnic = StringField('CNIC', validators=[Optional(), Length(max=20)])
    address = StringField('Address', validators=[Optional(), Length(max=500)])
    father_name = StringField('Father Name', validators=[Optional(), Length(max=200)])
    mother_name = StringField('Mother Name', validators=[Optional(), Length(max=200)])
    
    # Secondary Users (Read-Only from PO)
    secondary_user_name = StringField('Secondary User Name', validators=[Optional(), Length(max=200)])
    secondary_user_phone = StringField('Secondary User Phone', validators=[Optional(), Length(max=50)])
    emergency_user_name = StringField('Emergency User Name', validators=[Optional(), Length(max=200)])
    emergency_user_phone = StringField('Emergency User Phone', validators=[Optional(), Length(max=50)])
    
    # Installation Details (Read-Only from PO/Installer)
    segment = SelectField('Vehicle Segment', choices=[
        ('', 'Select Segment'),
        ('COMMERCIAL', 'Commercial'),
        ('PRIVATE', 'Private'),
        ('GOVERNMENT', 'Government'),
        ('FLEET', 'Fleet')
    ], validators=[Optional()])
    security_details = TextAreaField('Security Details', validators=[Optional()])
    installation_date = DateField('Installation Date', validators=[Optional()])
    technician_name = StringField('Technician Name', validators=[Optional(), Length(max=100)])
    device_location = StringField('Device Location', validators=[Optional(), Length(max=200)])
    sales_person_name = StringField('Sales Person', validators=[Optional(), Length(max=100)])
    
    # SSOT Installation Fields
    sim_network = StringField('SIM Network', validators=[Optional(), Length(max=100)])
    accessories_installed = StringField('Accessories Installed', validators=[Optional(), Length(max=500)])
    
    # Access Credentials (Editable by Security role)
    password_1 = StringField('Password 1', validators=[Optional(), Length(max=100)])
    password_2 = StringField('Password 2', validators=[Optional(), Length(max=100)])
    fence = StringField('Geo-fence', validators=[Optional(), Length(max=500)])
    services = TextAreaField('Services', validators=[Optional()])
    
    # Security Specific Checklists (Editable by Security role)
    security_training_completed = BooleanField('Security Training Completed', validators=[Optional()])
    customer_demonstration = BooleanField('Customer Demonstration Completed', validators=[Optional()])
    services_explained = BooleanField('Services and Charges Explained', validators=[Optional()])
    acknowledgement = BooleanField('Customer Acknowledgement Accepted', validators=[Optional()])
    
    # Status & Notes
    status = SelectField('Status', choices=[
        ('PENDING', 'Pending'),
        ('IN_PROGRESS', 'In Progress'),
        ('COMPLETED', 'Completed')
    ], validators=[DataRequired()])
    officer_notes = TextAreaField('Officer Notes', validators=[Optional()])
