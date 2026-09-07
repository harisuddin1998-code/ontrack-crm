# src/forms/payment_forms.py
"""
Payment Recovery Forms
"""
from flask_wtf import FlaskForm
from wtforms import FloatField, DateField, StringField, TextAreaField, SelectField
from wtforms.validators import DataRequired, Optional, NumberRange, Length


class PaymentForm(FlaskForm):
    """Add payment form"""
    amount = FloatField('Amount (PKR)', validators=[
        DataRequired(),
        NumberRange(min=0.01, message='Amount must be greater than 0')
    ])
    notes = TextAreaField('Notes', validators=[Optional(), Length(max=500)])
    payment_method = SelectField('Payment Method', choices=[
        ('ONLINE', 'Online Payment'),
        ('CASH', 'Cash Payment'),
        ('CHEQUE', 'Cheque'),
    ], validators=[Optional()])
    cheque_number = StringField('Cheque Number', validators=[Optional(), Length(max=50)])
    bank_name = StringField('Bank Name', validators=[Optional(), Length(max=100)])
    transaction_id = StringField('Transaction ID', validators=[Optional(), Length(max=100)])


class PaymentStatusForm(FlaskForm):
    """Update payment status form"""
    status = SelectField('Status', choices=[
        ('PENDING', 'Pending'),
        ('PARTIAL', 'Partial'),
        ('PAID', 'Paid'),
        ('OVERDUE', 'Overdue')
    ], validators=[DataRequired()])


class FollowUpForm(FlaskForm):
    """Schedule follow-up form"""
    next_follow_up = DateField('Next Follow-up Date', validators=[DataRequired()])
    notes = TextAreaField('Notes', validators=[Optional(), Length(max=500)]) 
