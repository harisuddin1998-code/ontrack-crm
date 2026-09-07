# src/forms/removal_forms.py
"""
Removal and Transfer Activity Forms
"""
from flask_wtf import FlaskForm
from wtforms import StringField, DateField, SelectField, TextAreaField, BooleanField
from wtforms.validators import DataRequired, Optional, Length


class TransferForm(FlaskForm):
    """Transfer activity form"""
    # Old Vehicle
    old_registration_no = StringField('Old Registration No', validators=[DataRequired(), Length(max=50)])
    old_make = StringField('Old Manufacturer', validators=[Optional(), Length(max=50)])
    old_model = StringField('Old Brand', validators=[Optional(), Length(max=50)])
    old_year = StringField('Old Year / Model', validators=[Optional(), Length(max=4)])
    old_color = StringField('Old Color', validators=[Optional(), Length(max=20)])
    old_chassis_no = StringField('Old Chassis No', validators=[Optional(), Length(max=100)])
    old_engine_no = StringField('Old Engine No', validators=[Optional(), Length(max=100)])
    old_customer_name = StringField('Old Customer Name', validators=[Optional(), Length(max=200)])
    old_customer_contact = StringField('Old Customer Contact', validators=[Optional(), Length(max=50)])
    old_imei_no = StringField('Old IMEI No', validators=[Optional(), Length(max=50)])
    old_sim_no = StringField('Old SIM No', validators=[Optional(), Length(max=50)])
    old_device_location = StringField('Old Device Location', validators=[Optional(), Length(max=200)])
    
    # New Vehicle
    new_registration_no = StringField('New Registration No', validators=[DataRequired(), Length(max=50)])
    new_make = StringField('New Manufacturer', validators=[Optional(), Length(max=50)])
    new_model = StringField('New Brand', validators=[Optional(), Length(max=50)])
    new_year = StringField('New Year / Model', validators=[Optional(), Length(max=4)])
    new_color = StringField('New Color', validators=[Optional(), Length(max=20)])
    new_chassis_no = StringField('New Chassis No', validators=[Optional(), Length(max=100)])
    new_engine_no = StringField('New Engine No', validators=[Optional(), Length(max=100)])
    new_customer_name = StringField('New Customer Name', validators=[Optional(), Length(max=200)])
    new_customer_contact = StringField('New Customer Contact', validators=[Optional(), Length(max=50)])
    
    # Transfer Details
    transfer_reason = TextAreaField('Transfer Reason', validators=[DataRequired()])
    device_transferred_date = DateField('Device Transferred Date', validators=[Optional()])


class RetainedForm(FlaskForm):
    """Retained activity form"""
    registration_no = StringField('Registration No', validators=[DataRequired(), Length(max=50)])
    make = StringField('Manufacturer', validators=[Optional(), Length(max=50)])
    model = StringField('Brand', validators=[Optional(), Length(max=50)])
    year = StringField('Year / Model', validators=[Optional(), Length(max=4)])
    color = StringField('Color', validators=[Optional(), Length(max=20)])
    chassis_no = StringField('Chassis No', validators=[Optional(), Length(max=100)])
    engine_no = StringField('Engine No', validators=[Optional(), Length(max=100)])
    customer_name = StringField('Customer Name', validators=[Optional(), Length(max=200)])
    customer_contact = StringField('Customer Contact', validators=[Optional(), Length(max=50)])
    imei_no = StringField('IMEI No', validators=[Optional(), Length(max=50)])
    sim_no = StringField('SIM No', validators=[Optional(), Length(max=50)])
    device_location = StringField('Device Location', validators=[Optional(), Length(max=200)])
    
    removal_reason = TextAreaField('Removal Reason', validators=[DataRequired()])
    removal_date = DateField('Removal Date', validators=[Optional()])
    removal_type = SelectField('Removal Type', choices=[
        ('RETAINED', 'Retained'),
        ('TRANSFERRED', 'Transferred'),
        ('DISPOSED', 'Disposed')
    ], validators=[Optional()], default='RETAINED')
    
    device_returned = BooleanField('Device Returned', default=False)
    return_date = DateField('Return Date', validators=[Optional()])
    device_condition = StringField('Device Condition', validators=[Optional(), Length(max=100)])
    retained_by = StringField('Retained By', validators=[Optional(), Length(max=100)])
    storage_location = StringField('Storage Location', validators=[Optional(), Length(max=200)])


class FlagVehicleForm(FlaskForm):
    """Flag vehicle for removal form"""
    registration_no = StringField('Registration No', validators=[DataRequired(), Length(max=50)])
    make = StringField('Manufacturer', validators=[Optional(), Length(max=50)])
    model = StringField('Brand', validators=[Optional(), Length(max=50)])
    year = StringField('Year / Model', validators=[Optional(), Length(max=4)])
    color = StringField('Color', validators=[Optional(), Length(max=20)])
    chassis_no = StringField('Chassis No', validators=[Optional(), Length(max=100)])
    engine_no = StringField('Engine No', validators=[Optional(), Length(max=100)])
    customer_name = StringField('Customer Name', validators=[Optional(), Length(max=200)])
    customer_contact = StringField('Customer Contact', validators=[Optional(), Length(max=50)])
    imei_no = StringField('IMEI No', validators=[Optional(), Length(max=50)])
    sim_no = StringField('SIM No', validators=[Optional(), Length(max=50)])
    device_location = StringField('Device Location', validators=[Optional(), Length(max=200)])
    
    flag_type = SelectField('Flag Type', choices=[
        ('REMOVAL', 'Removal'),
        ('RETENTION', 'Retention'),
        ('TRANSFER', 'Transfer')
    ], validators=[DataRequired()])
    priority = SelectField('Priority', choices=[
        ('LOW', 'Low'),
        ('NORMAL', 'Normal'),
        ('HIGH', 'High'),
        ('URGENT', 'Urgent')
    ], validators=[DataRequired()], default='NORMAL')
    flag_reason = TextAreaField('Reason for Flagging', validators=[DataRequired()])