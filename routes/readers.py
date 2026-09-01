"""
Readers blueprint - manages field workers and folder assignments.
"""

import hashlib
from flask import Blueprint, render_template, request, redirect, url_for, flash
from werkzeug.security import generate_password_hash

from routes.shared import ( client_service, period_service, template_service, folder_service, reader_service, PERIOD_MONTHS_HE, FOLDER_STATUS_HE, )

readers_bp = Blueprint('readers', __name__)

# מסך קוראים
# -----------

#  Helpers

def _enrich_reader_folders(reader_id, period_cache, client_templates_cache):
    """
    Helper: returns enriched folder list for a single reader.
    Silently returns [] on any error: a single reader's data issue should not break the whole readers screen.
    """
    try:
        folders = folder_service.get_reader_folders(reader_id)
    except Exception:
        return []
    
    enriched = []
    for f in folders:
        pid = f['period_id']
        if pid not in period_cache:
            period_cache[pid] = period_service.get_period(pid)
        period = period_cache[pid]
        if not period:
            continue
        
        cid = period['client_id']
        client = client_service.get_client(cid)
        if cid not in client_templates_cache:
            client_templates_cache[cid] = {
                t['template_id']: t
                for t in template_service.get_client_templates(cid)
            }
        tmpl = client_templates_cache[cid].get(f['template_id'], {})
        enriched.append({
            'folder_name': tmpl.get('folder_name', f'תיק {f["folder_id"]}'),
            'client_name': client['name'] if client else '-',
            'period_number': period['period_number'],
            'period_year': period['year'],
            'walk_order_start': tmpl.get('walk_order_start'),
            'walk_order_end': tmpl.get('walk_order_end'),
            'total_meters': f.get('total_meters') or 0,
            'completed_meters': f.get('completed_meters') or 0,
            'status': f.get('status', ''),
        })
    return enriched

def _build_assign_modal_data(client_templates_cache):
    """
    Helper: builds clients/periods/folders data for the assign-to-folder modal.
    Silently returns [] on any error: a single reader's data issue should not break the whole readers screen.
    """
    assign_clients = []
    assign_periods = []
    assign_folders = []
    seen_client_ids = set()
    seen_period_ids = set()
    
    for client in client_service.list_clients():
        cid = client['client_id']
        if cid not in client_templates_cache:
            client_templates_cache[cid] = {
                t['template_id']: t
                for t in template_service.get_client_templates(cid)
            }
        client_has_open = False
        for period in period_service.list_client_periods(cid):
            try:
                open_in_period = folder_service.list_open_folders_for_period(period['period_id'])
            except Exception:
                open_in_period = []
            
            if not open_in_period:
                continue
            
            if period['period_id'] not in seen_period_ids:
                seen_period_ids.add(period['period_id'])
                assign_periods.append({ 'period_id': period['period_id'], 'period_number': period['period_number'],
                    'period_year': period['year'], 'client_id': cid,})
            
            for f in open_in_period:
                tmpl = client_templates_cache[cid].get(f['template_id'], {})
                assign_folders.append({ 'folder_id': f['folder_id'],
                    'folder_name': tmpl.get('folder_name', f'תיק {f["folder_id"]}'), 'period_id': period['period_id'],})
            client_has_open = True
        
        if client_has_open and cid not in seen_client_ids:
            seen_client_ids.add(cid)
            assign_clients.append({'client_id': cid, 'client_name': client['name']})
    
    return {'assign_clients': assign_clients, 'assign_periods': assign_periods, 'assign_folders': assign_folders,}

def _build_readers_view(active_only):
    """Helper: assembles all data for the readers screen."""
    all_readers = reader_service.list_readers(active_only=active_only)
    
    # Shared caches across both helpers (avoid duplicate queries)
    period_cache = {}
    client_templates_cache = {}
    
    readers_data = []
    reader_folders_map = {}
    
    for r in all_readers:
        rd = dict(r)
        enriched = _enrich_reader_folders(r['reader_id'], period_cache, client_templates_cache)
        rd['folder_count'] = len(enriched)
        reader_folders_map[r['reader_id']] = enriched
        readers_data.append(rd)
    
    assign_data = _build_assign_modal_data(client_templates_cache)
    
    return {'readers': readers_data, 'reader_folders_map': reader_folders_map, **assign_data,}

#  Routes 

@readers_bp.route('/readers')
def readers():
    """Main readers screen: list of readers with their assigned folders and an assign-to-folder modal."""
    active_only = request.args.get('active_only', '0') == '1'
    view = _build_readers_view(active_only)
    
    return render_template(
        'readers.html',
        readers = view['readers'], reader_folders_map = view['reader_folders_map'],
        active_only = active_only, assign_clients = view['assign_clients'],
        assign_periods = view['assign_periods'], assign_folders = view['assign_folders'],
        period_months = PERIOD_MONTHS_HE, folder_status_he   = FOLDER_STATUS_HE,)

@readers_bp.route('/readers/create', methods=['POST'])
def create_reader():
    """Create a new reader"""
    name     = request.form.get('name', '').strip()
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '').strip()
    phone    = request.form.get('phone', '').strip() or None
    try:
        if not password:
            raise ValueError("סיסמה היא שדה חובה")
        password_hash = generate_password_hash(password)
        reader_service.create_reader(name, username, password_hash, phone)
        flash(f'קורא "{name}" נוצר בהצלחה', 'success')
    except ValueError as e:
        flash(str(e), 'error')
    return redirect(url_for('readers.readers'))

@readers_bp.route('/readers/<int:reader_id>/edit', methods=['POST'])
def edit_reader(reader_id):
    """Update a reader's name, username, and/or phone."""
    name     = request.form.get('name', '').strip() or None
    username = request.form.get('username', '').strip() or None
    phone    = request.form.get('phone', '').strip() or None
    try:
        reader_service.update_reader(reader_id, name=name, username=username, phone=phone)
        flash('הקורא עודכן בהצלחה', 'success')
    except ValueError as e:
        flash(str(e), 'error')
    return redirect(url_for('readers.readers'))

@readers_bp.route('/readers/<int:reader_id>/toggle-active', methods=['POST'])
def toggle_reader_active(reader_id):
    """Toggle a reader's active/inactive status."""
    try:
        reader = reader_service.get_reader(reader_id)
        if not reader:
            raise ValueError(f'קורא {reader_id} לא נמצא')
        if reader['active']:
            reader_service.deactivate_reader(reader_id)
            flash(f'קורא "{reader["name"]}" הושבת', 'success')
        else:
            reader_service.activate_reader(reader_id)
            flash(f'קורא "{reader["name"]}" הופעל', 'success')
    except ValueError as e:
        flash(str(e), 'error')
    return redirect(url_for('readers.readers'))

@readers_bp.route('/readers/<int:reader_id>/assign', methods=['POST'])
def assign_reader(reader_id):
    """Assign a reader to a work folder."""
    folder_id = request.form.get('folder_id', type=int)
    try:
        if not folder_id:
            raise ValueError('יש לבחור תיק עבודה')
        folder_service.assign_reader_to_folder(folder_id, reader_id)
        reader = reader_service.get_reader(reader_id)
        flash(f'קורא "{reader["name"]}" שויך לתיק בהצלחה', 'success')
    except ValueError as e:
        flash(str(e), 'error')
    return redirect(url_for('readers.readers'))