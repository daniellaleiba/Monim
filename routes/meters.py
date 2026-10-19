"""
Meters blueprint - displays and manages period meters.
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash

from routes.shared import (
    client_service, period_service, meter_service, folder_service, template_service, reader_service,
    fault_code_service, reading_service, shared_consumption_service, PERIOD_MONTHS_HE, WORK_STATUS_HE, to_json_safe,)

meters_bp = Blueprint('meters', __name__)

# מסך מונים
# ----------

#  Helpers 

def _build_meters_view(period_id, client_id):
    """
    Helper: assembles data for the meters screen.
    Folder-name lookup failures fall back to a generic "תיק {id}" label: a single broken folder shouldn't block the whole meters list.
    """
    meters = meter_service.get_period_meters(period_id)

    templates = template_service.get_client_templates(client_id)
    template_map = {t['template_id']: t for t in templates}

    # Enrich with folder names (batch one fetch per unique folder_id)
    folder_ids = {m['folder_id'] for m in meters if m.get('folder_id')}
    folder_names = {}
    for fid in folder_ids:
        try:
            folder = folder_service.get_folder(fid)
            if folder:
                tmpl = template_map.get(folder['template_id'], {})
                folder_number = tmpl.get('folder_number')
                folder_name = tmpl.get('folder_name') or (f'תיק {folder_number}' if folder_number else f'תיק {fid}')
                folder_names[fid] = folder_name
        except Exception:
            folder_names[fid] = f'תיק {fid}'

    for m in meters:
        m['folder_name']    = folder_names.get(m.get('folder_id'), '')
         # Placeholder until the field-reader mobile app exists 
        m['transmitted_at'] = None
        m['field_notes']    = None

    summary = meter_service.get_period_status_summary(period_id)

    return { 'meters': meters, 'summary': summary }

#  Routes 

@meters_bp.route('/meters/<int:period_id>')
def meters(period_id):
    """Main meters screen: full list with summary counts, optional folder pre-filter."""
    period = period_service.get_period(period_id)
    if not period:
        flash('תקופה לא נמצאה', 'error')
        return redirect(url_for('clients.clients'))

    client = client_service.get_client(period['client_id'])
    view = _build_meters_view(period_id, period['client_id'])
    
    # Convert to JSON-safe for template (template uses JavaScript)
    meters_json = [to_json_safe(m) for m in view['meters']]

    prefilter_folder_id = request.args.get('folder_id', type=int)
    summary = view['summary']
    folder_context = None

    if prefilter_folder_id:
        folder = folder_service.get_folder(prefilter_folder_id)
        if folder:
            templates = template_service.get_client_templates(period['client_id'])
            template_map = {t['template_id']: t for t in templates}
            tmpl = template_map.get(folder['template_id'], {})
            folder_name = tmpl.get('folder_name') or f'תיק {tmpl.get("folder_number", "?")}'
            folder_number = tmpl.get('folder_number')

            reader_name = None
            if folder.get('assigned_to'):
                reader = reader_service.get_reader(folder['assigned_to'])
                if reader:
                    reader_name = reader.get('name')

            folder_meters = [m for m in view['meters'] if m.get('folder_id') == prefilter_folder_id]
            summary = {'total': len(folder_meters)}
            for key in ('new', 'assigned_to_folder', 'assigned_to_reader', 'in_progress', 'completed', 'exception', 'missing_info'):
                summary[key] = sum(1 for m in folder_meters if m.get('work_status') == key)

            folder_context = { 'folder_name': folder_name, 'folder_number': folder_number,
                'reader_name': reader_name, 'total_meters': len(folder_meters), 'folder_id': prefilter_folder_id,}

    fault_codes = fault_code_service.get_as_dict()

    return render_template( 'meters.html', period = period, client= client,
        meters_json= meters_json, summary= summary, period_months = PERIOD_MONTHS_HE, work_status_he = WORK_STATUS_HE,
        prefilter_folder_id = prefilter_folder_id, folder_context = folder_context, fault_codes = fault_codes,)

@meters_bp.route('/meters/<int:period_meter_id>/estimate', methods=['GET'])
def estimate_meter(period_meter_id):
    """Calculate (without saving) an estimated reading for a single meter (used for live preview before the manager confirms)."""
    fault_code = request.args.get('fault_code', '').strip() or None
    try:
        result = meter_service.calculate_estimate(period_meter_id, fault_code)
        return {'ok': True, **result}
    except ValueError as e:
        return {'ok': False, 'error': str(e)}, 400

@meters_bp.route('/meters/<int:period_id>/bulk-estimate', methods=['POST'])
def bulk_estimate(period_id):
    """Calculate and save estimates for all eligible meters in a period/folder."""
    folder_id = request.json.get('folder_id') or None
    try:
        result = meter_service.bulk_estimate(period_id, folder_id)
        return {'ok': True, **result}
    except ValueError as e:
        return {'ok': False, 'error': str(e)}, 400

@meters_bp.route('/meters/<int:period_id>/shared-consumption', methods=['POST'])
def shared_consumption(period_id):
    """Trigger shared-consumption calculation for all buildings in a period/folder."""
    folder_id = request.json.get('folder_id') or None
    try:
        result = shared_consumption_service.calculate(period_id=period_id, folder_id=folder_id)
        return {'ok': True, **result}
    except ValueError as e:
        return {'ok': False, 'error': str(e)}, 400

@meters_bp.route('/meters/<int:period_meter_id>/update-status', methods=['POST'])
def update_meter_status(period_meter_id):
    """Manually update a meter's work_status and/or fault_code."""
    new_status = request.form.get('work_status', '').strip()
    fault_code = request.form.get('fault_code', '').strip() or None
    period_id = request.form.get('period_id', type=int)
    try: 
        meter_service.update_fault_code(period_meter_id, fault_code)
        meter_service.update_work_status(period_meter_id, new_status)
        flash('המונה עודכן', 'success')
    except ValueError as e:
        flash(str(e), 'error')
    return redirect(url_for('meters.meters', period_id=period_id))

@meters_bp.route('/meters/<int:period_meter_id>/update-manager', methods=['POST'])
def update_meter_manager(period_meter_id):
    """
    Manager-side manual edit of a meter's current reading state (JSON API).
    Optionally also updates work_status in the same request if provided.
    """
    data = request.get_json()
    if not data:
        return {'ok': False, 'error': 'אין נתונים'}, 400
    try:
        meter_service.apply_reading_to_current_state( period_meter_id, fault_code= data.get('fault_code') or None,
            current_reading = data.get('current_reading'), addon = data.get('addon'),
            reading_time= data.get('reading_time') or None,  # ISO string מלא: "2026-05-10T14:30:00"
            is_estimated = data.get('is_estimated') or False,
        )
        # Manager notes - if the key was sent (null/empty clears the notes)
        if 'manager_notes' in data:
            meter_service.update_manager_notes(period_meter_id, data['manager_notes'])
        #Save job status - if sent
        work_status = data.get('work_status')
        if work_status:
            meter_service.update_work_status(period_meter_id, work_status)

        meter = meter_service.get_meter(period_meter_id)
        consumption = meter.get('consumption')
        return {
            'ok': True,
            'consumption': float(consumption) if consumption is not None else None,
            'work_status': meter.get('work_status'),
        }
    except ValueError as e:
        return {'ok': False, 'error': str(e)}, 400