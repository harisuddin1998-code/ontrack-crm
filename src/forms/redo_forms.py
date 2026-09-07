# src/forms/redo_forms.py
"""
REDO Activity Forms - Refactored Control Specification
"""
from flask_wtf import FlaskForm
from wtforms import StringField, DateField, SelectField, TextAreaField, BooleanField
from wtforms.validators import DataRequired, Optional, Length


class RedoForm(FlaskForm):
    """Refactored REDO Activity Form"""
    
    # Activity Details - REDO only
    activity_type = SelectField('Activity Type', choices=[
        ('REDO', 'REDO'),
    ], validators=[DataRequired()])
    scheduled_date = DateField('Scheduled Date', validators=[Optional()])

    # Customer Details
    customer_name = StringField('Customer Name', validators=[DataRequired(), Length(max=200)])
    customer_contact = StringField('Contact Number', validators=[Optional(), Length(max=50)])
    # Read off the vehicle's Purchase Order by the lookup, not chosen here.
    # This was a dropdown of hardcoded names ('Ali', 'Usman', 'Direct Sales'),
    # which meant the salesperson recorded against a service visit was a
    # guess unconnected to the order that actually sold the vehicle. The
    # template renders it read-only, like the other PO-sourced fields.
    sale_person = StringField('Sales Person', validators=[Optional(), Length(max=100)])
    arranged_by = StringField('Arranged By', validators=[Optional(), Length(max=100)])

    # Vehicle Details - auto-pulled from the DB lookup and hardcoded
    # (read-only) in the template rather than picked from a dropdown, since
    # the real data is whatever's on record, not a preset list of options.
    registration_no = StringField('Reg. No.', validators=[DataRequired(), Length(max=50)])
    make = StringField('Manufacturer', validators=[Optional(), Length(max=50)])
    model = StringField('Brand', validators=[Optional(), Length(max=50)])
    year = StringField('Year / Model', validators=[Optional(), Length(max=4)])
    color = StringField('Color', validators=[Optional(), Length(max=20)])
    chassis_no = StringField('Chassis No.', validators=[Optional(), Length(max=100)])
    engine_no = StringField('Engine No.', validators=[Optional(), Length(max=100)])

    # Device Details
    imei_no = StringField('IMEI No.', validators=[Optional(), Length(max=50)])
    sim_no = StringField('SIM No.', validators=[Optional(), Length(max=50)])
    device_type = SelectField('Device Type', choices=[
        ('', '-- Select Device Type --'),
        ('GPS Tracker 4G', 'GPS Tracker 4G'),
        ('GPS Tracker 2G', 'GPS Tracker 2G'),
        ('OBD Tracker', 'OBD Tracker'),
        ('Wireless Battery Tracker', 'Wireless Battery Tracker')
    ], validators=[Optional()])
    device_location = StringField('Device Location', validators=[Optional(), Length(max=200)])
    old_imei_no = StringField('Old IMEI No.', validators=[Optional(), Length(max=50)])
    old_sim_no = StringField('Old SIM No.', validators=[Optional(), Length(max=50)])
    new_device = StringField('New Device', validators=[Optional(), Length(max=50)])
    new_sim = StringField('New SIM', validators=[Optional(), Length(max=50)])
    device_change_reason = SelectField('Device Change Reason', choices=[
        ('', 'Select reason...'),
        ('Power Issue', 'Power Issue'),
        ('Device Damage', 'Device Damage'),
        ('Device Missing', 'Device Missing'),
    ], validators=[Optional()])

    # Technical & Operations Details
    transfer_installation = SelectField('T-Installation', choices=[
        ('No', 'No'),
        ('Yes', 'Yes')
    ], validators=[Optional()])
    transfer_charges = StringField('Transfer Charges', validators=[Optional(), Length(max=50)])
    city = StringField('City', validators=[Optional(), Length(max=100)])
    vehicle_location = StringField('Vehicle Location', validators=[Optional(), Length(max=200)])
    technician = SelectField('Technician', choices=[], validators=[Optional()])  # Populated dynamically
    tested_by = StringField('Testing By', validators=[Optional(), Length(max=100)])
    fuel = StringField('Fuel Compensated', validators=[Optional(), Length(max=50)])

    # Resolution & Remarks
    resolution_status = SelectField('Resolution Status', choices=[
        ('Pending', 'Pending'),
        ('Completed', 'Completed'),
        ('Cancelled', 'Cancelled')
    ], validators=[DataRequired()])
    remarks = TextAreaField('Remarks', validators=[Optional()])


class NonReportingConversationForm(FlaskForm):
    """Non-reporting vehicle conversation form with technician selection"""
    conversation_type = SelectField('Conversation Type', choices=[
        ('PHONE_CALL', 'Phone Call'),
        ('WHATSAPP', 'WhatsApp Message'),
    ], validators=[DataRequired()])
    
    direction = SelectField('Direction', choices=[
        ('IN', 'Incoming'),
        ('OUT', 'Outgoing')
    ], validators=[DataRequired()])
    
    contact_person = StringField('Contact Person', validators=[Optional(), Length(max=100)])
    contact_number = StringField('Contact Number', validators=[Optional(), Length(max=50)])
    technician_id = SelectField('Assign Technician', choices=[], validators=[Optional()])
    summary = TextAreaField('Conversation Summary', validators=[DataRequired()])
    action_taken = TextAreaField('Action Taken', validators=[Optional()])
    follow_up_required = BooleanField('Follow-up Required', default=False)
    follow_up_date = DateField('Follow-up Date', validators=[Optional()])