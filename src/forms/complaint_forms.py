# src/forms/complaint_forms.py
"""
Complaint Forms
"""
from flask_wtf import FlaskForm
from wtforms import StringField, TextAreaField, SelectField, SubmitField
from wtforms.validators import DataRequired, Optional


class ComplaintForm(FlaskForm):
    """Form for logging a new customer complaint"""
    customer_name = StringField('Customer / Client Name', validators=[DataRequired()])
    customer_contact = StringField('Contact Number', validators=[DataRequired()])
    reg_no = StringField('Vehicle Reg No (Optional)', validators=[Optional()])
    city = StringField('City', validators=[Optional()])
    vehicle_location = StringField('Unit / Device Location', validators=[Optional()])
    
    complaint_type = SelectField('Complaint Type', choices=[
        ('GPS_NOT_WORKING', 'GPS Device Not Working / Offline'),
        ('INCORRECT_LOCATION', 'Incorrect GPS Location / Drifting'),
        ('ENGINE_CUTOFF_ISSUE', 'Engine Cutoff / Immobilizer Issue'),
        ('DEVICE_TAMPERED', 'Physical Device Tampering / Wire Cut'),
        ('APP_LOGIN_ISSUE', 'Mobile App / Web Portal Login Issue'),
        ('BILLING_DISPUTE', 'Billing / AMC Charges Dispute'),
        ('OTHER', 'Other Customer Inquiry')
    ], validators=[DataRequired()])
    
    severity = SelectField('Severity', choices=[
        ('LOW', 'Low - Informational'),
        ('MEDIUM', 'Medium - Standard SLA'),
        ('HIGH', 'High - Urgent Attention'),
        ('CRITICAL', 'Critical - Emergency')
    ], default='MEDIUM', validators=[DataRequired()])
    
    description = TextAreaField('Complaint Description', validators=[DataRequired()])
    # Choices come from the Technician Management roster - see
    # TechnicianService.get_roster - so only a real, active technician can be
    # put on a ticket.
    technician_id = SelectField('Assign Technician', coerce=int, validators=[Optional()])
    submit = SubmitField('Log Complaint Ticket')


class ComplaintResolveForm(FlaskForm):
    """Form for resolving or updating complaint ticket status"""
    status = SelectField('Status', choices=[
        ('OPEN', 'Open'),
        ('IN_PROGRESS', 'In Progress'),
        ('RESOLVED', 'Resolved'),
        ('CLOSED', 'Closed')
    ], validators=[DataRequired()])
    
    resolution_notes = TextAreaField('Resolution / Update Notes', validators=[DataRequired()])
    submit = SubmitField('Save Update')
