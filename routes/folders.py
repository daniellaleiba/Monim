"""
Folders blueprint - manages folder templates and work folder distribution.
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash

from routes.shared import (client_service, period_service, meter_service, template_service, folder_service,
    reader_service, PERIOD_MONTHS_HE, FOLDER_STATUS_HE,)

folders_bp = Blueprint('folders', __name__)

# מסך חלוקה לתיקים
# -----------------

#  Helpers

def _build_folders_view(period_id, client_id):
    """Helper: assembles data for the folders screen: templates, work folders (enriched with names/readers), and meter counts."""
    templates = template_service.get_client_templates(client_id)
    template_map = {t['template_id']: t for t in templates}

    readers = reader_service.list_readers(active_only=True)
    reader_name_map = {r['reader_id']: r['name'] for r in readers}

    work_folders_raw = folder_service.get_period_folders(period_id)
    work_folders = []
    for f in work_folders_raw:
        fd = dict(f)
        tmpl = template_map.get(f['template_id'], {})
        fd['folder_name'] = tmpl.get('folder_name', f'תיק {tmpl.get("folder_number","?")}')
        fd['folder_number'] = tmpl.get('folder_number')
        fd['walk_order_start'] = tmpl.get('walk_order_start')
        fd['walk_order_end'] = tmpl.get('walk_order_end')
        fd['reader_name'] = reader_name_map.get(f.get('assigned_to'))
        work_folders.append(fd)

    return { 'templates': templates, 'work_folders': work_folders, 'readers': readers,
        'total_meters': meter_service.count_period_meters(period_id), 'unassigned': meter_service.count_unassigned(period_id),}

#  Routes

@folders_bp.route('/folders/<int:period_id>')
def folders(period_id):
    """Main folder-distribution screen for a period."""
    period = period_service.get_period(period_id)
    if not period:
        flash('תקופה לא נמצאה', 'error')
        return redirect(url_for('clients.clients'))
    
    client = client_service.get_client(period['client_id'])
    view = _build_folders_view(period_id, period['client_id'])
    
    return render_template( 'folders.html',
        period = period, client = client, templates= view['templates'], work_folders = view['work_folders'],
        readers  = view['readers'], total_meters = view['total_meters'], unassigned = view['unassigned'],
        period_months = PERIOD_MONTHS_HE, folder_status_he = FOLDER_STATUS_HE,)

@folders_bp.route('/folders')
def all_folders():
    """Global folders overview across all clients/periods, optionally filtered to non-completed."""
    active_only = request.args.get('active_only', type=int)
    folders = folder_service.get_all_folders_overview()
    if active_only:
        folders = [f for f in folders if f['folder_status'] != 'completed']
    return render_template(
        'folders_overview.html',
        folders = folders, active_only = active_only, folder_status_he = FOLDER_STATUS_HE, period_months = PERIOD_MONTHS_HE, )

@folders_bp.route('/folders/<int:period_id>/create-template', methods=['POST'])
def create_template(period_id):
    """Create a new folder template for the period's client."""
    period = period_service.get_period(period_id)
    if not period:
        flash('תקופה לא נמצאה', 'error')
        return redirect(url_for('clients.clients'))
    try:
        folder_number= int(request.form.get('folder_number', 0))
        folder_name= request.form.get('folder_name', '').strip()
        walk_order_start= int(request.form.get('walk_order_start', 0))
        walk_order_end= int(request.form.get('walk_order_end', 0))
        template_service.create_template( client_id= period['client_id'], folder_number= folder_number,
            folder_name = folder_name, walk_order_start = walk_order_start, walk_order_end = walk_order_end,)
        flash(f'תבנית "{folder_name or f"תיק {folder_number}"}" נוצרה', 'success')
    except (ValueError, TypeError) as e:
        flash(str(e), 'error')
    return redirect(url_for('folders.folders', period_id=period_id))

@folders_bp.route('/folders/template/<int:template_id>/edit', methods=['POST'])
def edit_template(template_id):
    """Update a folder template's number, name, and/or walk-order range."""
    period_id = request.form.get('period_id', type=int)
    try:
        fn= request.form.get('folder_number')
        name = request.form.get('folder_name', '').strip() or None
        start = request.form.get('walk_order_start')
        end = request.form.get('walk_order_end')
        template_service.update_template(
            template_id = template_id, folder_name= name,
            folder_number = int(fn) if fn   else None,
            walk_order_start = int(start) if start else None,
            walk_order_end= int(end) if end  else None,
        )
        flash('התבנית עודכנה', 'success')
    except (ValueError, TypeError) as e:
        flash(str(e), 'error')
    return redirect(
        url_for('folders.folders', period_id=period_id) if period_id 
        else url_for('clients.clients')
    )


@folders_bp.route('/folders/template/<int:template_id>/delete', methods=['POST'])
def delete_template(template_id):
    """
    Delete a folder template.
    Note: will fail with an unhandled DB error (caught here as a generic message) if any work_folder still references this template.
            See FolderTemplateService.delete_template() for the underlying RESTRICT risk.
    """
    period_id = request.form.get('period_id', type=int)
    try:
        template_service.delete_template(template_id)
        flash('התבנית נמחקה', 'success')
    except ValueError as e:
        flash(str(e), 'error')
    except Exception:
        flash('לא ניתן למחוק תבנית זו , ייתכן שקיימים תיקי עבודה שנוצרו ממנה', 'error')

    return redirect(
        url_for('folders.folders', period_id=period_id) if period_id 
        else url_for('clients.clients')
    )


@folders_bp.route('/folders/<int:period_id>/create-folders', methods=['POST'])
def create_folders(period_id):
    """Create work folders from all client templates for this period, then auto-distribute meters into them."""
    try:
        created = folder_service.create_folders_for_period(period_id)
        flash(f'נוצרו {len(created)} תיקי עבודה', 'success')
        
        # חלק מונים אוטומטית מיד אחרי יצירת התיקים
        result = folder_service.distribute_meters_into_folders(period_id)
        assigned  = result.get('assigned', 0)
        unmatched = result.get('unmatched', 0)
        flash(f'חולקו {assigned} מונים לתיקים', 'success')
        if unmatched:
            flash(f'{unmatched} מונים לא שויכו , סדר הליכה לא מכוסה על ידי אף תבנית', 'error')
            
    except ValueError as e:
        flash(str(e), 'error')
    return redirect(url_for('folders.folders', period_id=period_id))

@folders_bp.route('/folders/folder/<int:folder_id>/delete', methods=['POST'])
def delete_folder(folder_id):
    """Delete a work folder (its meters are released automatically.)"""
    period_id = request.form.get('period_id', type=int)
    try:
        folder_service.delete_folder(folder_id)
        flash('התיק נמחק והמונים שוחררו', 'success')
    except ValueError as e:
        flash(str(e), 'error')
    return redirect(url_for('folders.folders', period_id=period_id))

@folders_bp.route('/folders/<int:period_id>/assign-reader', methods=['POST'])
def assign_reader_to_folder(period_id):
    """
    Assign a reader to a folder: if the folder already has a different reader, unassigns them first (reassign).
    Not atomic: if unassign succeeds but the new assign fails, the folder is left with no reader.
    """
    folder_id = request.form.get('folder_id', type=int)
    reader_id = request.form.get('reader_id', type=int)
    try:
        if not folder_id or not reader_id:
            raise ValueError('יש לבחור תיק עבודה וקורא')
        folder = folder_service.get_folder(folder_id)
        if folder and folder.get('assigned_to') and folder['assigned_to'] != reader_id:
            folder_service.unassign_reader_from_folder(folder_id)
        folder_service.assign_reader_to_folder(folder_id, reader_id)
        flash('הקורא שויך לתיק בהצלחה', 'success')
    except ValueError as e:
        flash(str(e), 'error')
    return redirect(url_for('folders.folders', period_id=period_id))

@folders_bp.route('/folders/<int:period_id>/release-folder', methods=['POST'])
def release_folder(period_id):
    """Release a folder to its reader's mobile app (re-release allowed). The checkbox is sent only when checked."""
    folder_id = request.form.get('folder_id', type=int)
    include_previous_readings = request.form.get('include_previous_readings') is not None
    try:
        if not folder_id:
            raise ValueError('יש לבחור תיק עבודה')
        folder_service.release_folder(folder_id, include_previous_readings)
        flash('התיק שוחרר לקורא', 'success')
    except ValueError as e:
        flash(str(e), 'error')
    return redirect(url_for('folders.folders', period_id=period_id))

