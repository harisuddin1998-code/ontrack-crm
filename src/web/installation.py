# src/web/installation.py
"""
Installation Routes - Installation dashboard and updates
"""
from flask import render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user

from src.web import installation_bp
from src.extensions import db
from src.services import POService, TechnicianService, DeviceTypeService, GPSService
from src.services.notification_service import NotificationService
from src.forms.po_forms import InstallationUpdateForm
from src.utils.decorators import role_required
from src.utils.logging import get_logger

logger = get_logger(__name__)


@installation_bp.route('/dashboard')
@login_required
@role_required('installation', 'admin', 'executive')
def dashboard():
    """Installation dashboard - View all POs"""
    po_service = POService()
    
    status_filter = request.args.get('status', '')
    search = request.args.get('search', '')
    
    filters = {}
    if status_filter:
        filters['status'] = status_filter
    
    result = po_service.get_pos(filters=filters, search=search)
    orders = result['items']
    
    stats = po_service.get_dashboard_stats()
    
    return render_template('installation/dashboard.html',
                         orders=orders,
                         stats=stats,
                         search=search,
                         status_filter=status_filter)


@installation_bp.route('/po/<int:po_id>', methods=['GET', 'POST'])
@login_required
@role_required('installation', 'admin')
def update_po(po_id):
    """Update installation details.

    The installation team records what was fitted. The Administrator can, in
    addition, edit every other field on the order - customer, contact, driver,
    registration, sales person, the existing-vehicle details and the money.
    Those fields are rendered only for an admin and read back only for an
    admin, so an installer cannot reach them by any route.
    """
    po_service = POService()
    po = po_service.get_po(po_id)

    if not po:
        flash('PO not found', 'danger')
        return redirect(url_for('installation.dashboard'))

    is_admin = current_user.is_admin()
    form = InstallationUpdateForm(obj=po)

    # Populate vehicle, city, and technician choices
    from src.services.vehicle_service import (
        VehicleMakeService, VehicleModelService, VehicleYearService, VehicleColorService, CityService
    )
    form.vehicle_make.choices = [('', 'Select Make')] + [(m.name, m.name) for m in VehicleMakeService().get_all_makes()]
    form.vehicle_model.choices = [('', 'Select Model')] + [(m.name, m.name) for m in VehicleModelService().get_all()]
    form.vehicle_year.choices = [('', 'Select Year')] + VehicleYearService().get_year_choices()
    form.vehicle_color.choices = [('', 'Select Color')] + [(c.name, c.name) for c in VehicleColorService().get_all_colors()]
    form.city.choices = [('', 'Select City')] + [(c.name, c.name) for c in CityService().get_all_cities()]

    # Only the Administrator gets the sales-person picker, so only they pay
    # for building its list.
    if is_admin:
        from src.services.user_service import UserService
        form.sales_person_id.choices = [('', 'Select Sales Person')] + [
            (u.id, u.name or u.username) for u in UserService().get_sales_users()]


    # Pre-populate fields stored on SecurityBriefingData
    from src.models.security import SecurityBriefingData
    briefing = SecurityBriefingData.query.filter_by(po_id=po_id).first()
    if briefing and request.method == 'GET':
        form.sim_network.data = briefing.sim_network or ''
        form.accessories_installed.data = briefing.accessories_installed or ''
    
    # The Technician Management roster, the same list every other technician
    # picker in the CRM reads.
    from src.services.technician_service import TechnicianService
    technicians = TechnicianService.get_roster()
    logger.info(f"Loaded {len(technicians)} technicians for dropdown")
    
    # Populate technician choices
    form.technician_assigned.choices = [('', 'Select Technician')] + [
        (tech.name, tech.name) for tech in technicians
    ]
    
    # Populate device type choices
    try:
        devices = DeviceTypeService().get_all_device_types()
        form.device_type.choices = [('', 'Select Device Type')] + [
            (d.name, d.name) for d in devices
        ]
    except Exception as e:
        logger.error(f"Error loading device types: {e}")
        form.device_type.choices = [('', 'Select Device Type')]
    
    # Handle POST request - verify technician exists
    if request.method == 'POST':
        technician_name = request.form.get('technician_assigned', '')
        if technician_name:
            from src.models.technician import Technician
            tech = Technician.query.filter_by(name=technician_name, is_active=True).first()
            if not tech:
                flash(f'⚠️ Technician "{technician_name}" not found or inactive', 'warning')
                form.technician_assigned.data = ''
    
    if form.validate_on_submit():
        # Who was on the order before this save, so the notification below
        # fires on the change rather than on every save of an order that
        # already had a technician.
        previous_technician = (po.technician_assigned or '').strip().upper()

        data = {
            'vehicle_make': form.vehicle_make.data.upper() if form.vehicle_make.data else po.vehicle_make,
            'vehicle_model': form.vehicle_model.data.upper() if form.vehicle_model.data else po.vehicle_model,
            'vehicle_year': form.vehicle_year.data if form.vehicle_year.data else po.vehicle_year,
            'vehicle_color': form.vehicle_color.data.upper() if form.vehicle_color.data else po.vehicle_color,
            'transmission': form.transmission.data or po.transmission,
            'power_cc': form.power_cc.data.strip() if form.power_cc.data else po.power_cc,
            'engine_number': form.engine_number.data.upper() if form.engine_number.data else po.engine_number,
            'chassis_number': form.chassis_number.data.upper() if form.chassis_number.data else po.chassis_number,
            'city': form.city.data.upper() if form.city.data else po.city,
            'scheduled_date': form.scheduled_date.data,
            'technician_assigned': form.technician_assigned.data.upper() if form.technician_assigned.data else None,
            'imei_no': form.imei_no.data.upper() if form.imei_no.data else None,
            'sim_no': form.sim_no.data.upper() if form.sim_no.data else None,
            'device_type': form.device_type.data.upper() if form.device_type.data else None,
            'device_location': form.device_location.data.upper() if form.device_location.data else None,
            'fuel': form.fuel.data,
            'arranged_by_sales_person': form.arranged_by_sales_person.data.upper() if form.arranged_by_sales_person.data else None,
            'vehicle_availability_location': form.vehicle_availability_location.data.upper() if form.vehicle_availability_location.data else None,
            'remarks': form.remarks.data.upper() if form.remarks.data else None,
            'status': form.status.data,
        }
        
        # If status is COMPLETED, also set tested_by
        if form.status.data == 'COMPLETED':
            data['tested_by'] = current_user.username.upper()
            logger.info(f"PO {po.po_number} marked as COMPLETED by {current_user.username}")

        # The rest of the order's own particulars, for the Administrator
        # alone. Blank is "leave it as it is" rather than "erase it", so an
        # admin who edits only the rate does not wipe the customer's name;
        # and `sales_person_id` is only written when a person was actually
        # picked, since an empty select must not orphan the order.
        if is_admin:
            admin_fields = {
                'owner_name': form.owner_name.data,
                'owner_contact': form.owner_contact.data,
                'contact_person_driver': form.contact_person_driver.data,
                'reg_no': form.reg_no.data,
                'existing_customer_name': form.existing_customer_name.data,
                'existing_vehicle_number': form.existing_vehicle_number.data,
            }
            for field, value in admin_fields.items():
                if value and value.strip():
                    data[field] = value.strip().upper()

            if form.tested_by.data and form.tested_by.data.strip():
                data['tested_by'] = form.tested_by.data.strip().upper()
            if form.rates.data is not None:
                data['rates'] = form.rates.data
            if form.amc.data is not None:
                data['amc'] = form.amc.data
            if form.sales_person_id.data:
                data['sales_person_id'] = int(form.sales_person_id.data)


        # Save installer-specific fields to SecurityBriefingData
        briefing_fields = {
            'sim_network': form.sim_network.data.upper() if form.sim_network.data else None,
            'accessories_installed': form.accessories_installed.data.upper() if form.accessories_installed.data else None,
        }
        
        try:
            updated_po = po_service.update_installation_details(
                po_id, data, current_user.id, include_order_fields=is_admin)

            # Update or create SecurityBriefingData for installer fields
            from src.models.security import SecurityBriefingData
            briefing = SecurityBriefingData.query.filter_by(po_id=po_id).first()
            if not briefing:
                briefing = SecurityBriefingData(po_id=po_id, status='PENDING')
                db.session.add(briefing)
            for key, val in briefing_fields.items():
                setattr(briefing, key, val)
            db.session.commit()

            # Keep Inventory in sync: if the installed IMEI matches a known
            # inventory unit, flip it to INSTALLED against this vehicle.
            if updated_po and updated_po.imei_no:
                from src.services.inventory_service import InventoryService
                InventoryService().mark_installed_if_known(updated_po.imei_no, updated_po.reg_no)

            # Tell the salesperson their order has a technician on it. Only
            # on the change: re-saving an order that already had one is not
            # news, and the customer has already been told.
            assigned = (updated_po.technician_assigned or '').strip() if updated_po else ''
            if assigned and assigned.upper() != previous_technician:
                try:
                    NotificationService().notify_technician_assigned(updated_po, assigned)
                except Exception as e:
                    logger.error(f"Failed to notify of technician assignment: {e}")

            if updated_po and updated_po.status == 'COMPLETED':
                flash(f'Installation for PO {po.po_number} marked as COMPLETED! Email notification sent.', 'success')
            else:
                flash(f'Installation details for PO {po.po_number} updated!', 'success')
            
            return redirect(url_for('installation.dashboard'))
        except Exception as e:
            logger.error(f"Error updating PO: {e}")
            flash(f'❌ Error updating PO: {str(e)}', 'danger')
    
    # If form validation fails, show errors
    if form.errors:
        for field, errors in form.errors.items():
            for error in errors:
                flash(f'{field}: {error}', 'danger')
    
    from src.services.vehicle_service import VehicleModelService
    return render_template('installation/update_po.html',
                         form=form,
                         po=po,
                         is_admin=is_admin,
                         technicians=technicians,
                         # Picking a make narrows the model list in the browser
                         # - see templates/_make_model_filter.html.
                         make_model_map=VehicleModelService().get_make_model_map())


@installation_bp.route('/get-technician-location/<string:technician_name>')
@login_required
def get_technician_location(technician_name):
    """AJAX endpoint to get technician's current location from their bike IMEI"""
    try:
        from src.models.technician import Technician
        from src.models.technician import TechnicianBike
        
        # Get technician directly
        tech = Technician.query.filter_by(name=technician_name).first()
        
        if not tech:
            return jsonify({'success': False, 'error': 'Technician not found'}), 404
        
        # Get bike directly from TechnicianBike table using technician_id
        bike = TechnicianBike.query.filter_by(technician_id=tech.id, is_active=True).first()
        
        if not bike:
            return jsonify({
                'success': False,
                'error': 'No bike assigned to this technician',
                'has_bike': False
            }), 404
        
        if not bike.imei:
            return jsonify({
                'success': False,
                'error': 'Bike has no IMEI assigned',
                'has_bike': True,
                'bike_registration': bike.bike_registration
            }), 404
        
        # Get GPS location for this IMEI
        gps_service = GPSService()
        location = gps_service.get_location_by_imei(bike.imei)
        
        if location:
            return jsonify({
                'success': True,
                'is_reporting': True,
                'imei': bike.imei,
                'bike_registration': bike.bike_registration,
                'location': {
                    'lat': location.get('lat'),
                    'lng': location.get('lng'),
                    'address': location.get('address'),
                    'speed': location.get('speed'),
                    'last_updated': location.get('last_updated')
                }
            })
        else:
            return jsonify({
                'success': True,
                'is_reporting': False,
                'imei': bike.imei,
                'bike_registration': bike.bike_registration,
                'error': 'Device not reporting GPS'
            })
            
    except Exception as e:
        logger.error(f"Error fetching technician location: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@installation_bp.route('/gps-location/<string:imei>')
@login_required
def get_gps_location(imei):
    """AJAX endpoint to fetch GPS location for a vehicle IMEI"""
    try:
        gps_service = GPSService()
        location = gps_service.get_location_by_imei(imei)
        
        if location:
            return jsonify({
                'success': True,
                'lat': location.get('lat'),
                'lng': location.get('lng'),
                'address': location.get('address'),
                'speed': location.get('speed'),
                'last_updated': location.get('last_updated')
            })
        else:
            return jsonify({
                'success': False,
                'error': 'No GPS location found for this IMEI',
                'is_reporting': False
            }), 404
    except Exception as e:
        logger.error(f"Error fetching GPS location: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@installation_bp.route('/update-technician-location', methods=['POST'])
@login_required
def update_technician_location():
    """Update technician's home latitude and longitude from GPS data"""
    try:
        from src.models.technician import Technician

        data = request.get_json()
        technician_name = data.get('technician_name')
        lat = data.get('lat')
        lng = data.get('lng')
        address = data.get('address')
        
        if not technician_name or lat is None or lng is None:
            return jsonify({
                'success': False,
                'error': 'Missing required data'
            }), 400
        
        # Find technician
        tech = Technician.query.filter_by(name=technician_name).first()
        if not tech:
            return jsonify({
                'success': False,
                'error': 'Technician not found'
            }), 404
        
        # Update technician's home location
        tech.home_lat = str(lat)
        tech.home_lng = str(lng)
        
        # If address is provided, update that too
        if address:
            tech.address = address
        
        db.session.commit()
        
        logger.info(f"✅ Updated location for technician {technician_name}: Lat={lat}, Lng={lng}")
        
        return jsonify({
            'success': True,
            'message': f'Location updated for {technician_name}',
            'technician': {
                'name': tech.name,
                'home_lat': tech.home_lat,
                'home_lng': tech.home_lng,
                'address': tech.address
            }
        })
        
    except Exception as e:
        logger.error(f"Error updating technician location: {e}")
        db.session.rollback()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500