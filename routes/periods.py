"""
Periods blueprint - manages reading periods, file uploads, and processing.
"""

import os
import uuid
import logging
from collections import defaultdict
from datetime import date
from werkzeug.utils import secure_filename
from flask import Blueprint, render_template, request, redirect, url_for, flash

from routes.shared import (
    client_service, period_service, folder_service, source_file_service,
    meter_service, UPLOAD_DIR, PERIOD_MONTHS_HE, PERIOD_STATUS_HE, FILE_STATUS_HE, )

periods_bp = Blueprint('periods', __name__)

logger = logging.getLogger(__name__)

# מסך תקופות
# -----------

#  Helpers 

def _build_periods_view(client_id):
    """Helper: assembles data for the periods screen."""
    all_periods = period_service.list_client_periods(client_id)
    
    for p in all_periods:
        p['source_file'] = source_file_service.get_period_source_file(p['period_id'])
        try:
            p['meter_count'] = meter_service.count_period_meters(p['period_id'])
        except Exception:
            p['meter_count'] = 0  # graceful fallback: a count failure shouldn't break the whole screen
    
    by_year = defaultdict(list)
    for p in all_periods:
        by_year[p['year']].append(p)
    
    # Sort periods within year ascending (1 → 6)
    for year in by_year:
        by_year[year].sort(key=lambda p: p['period_number'])
    
    years = sorted(by_year.keys(), reverse=True)
    
    return { 'years': years, 'by_year': dict(by_year),}

#  Routes 

@periods_bp.route('/periods/<int:client_id>')
def periods(client_id):
    """Main periods screen for a client: shows all years/periods with file status."""
    client = client_service.get_client(client_id)
    if not client:
        flash('תאגיד לא נמצא', 'error')
        return redirect(url_for('clients.clients'))

    view = _build_periods_view(client_id)

    current_year = date.today().year
    return render_template(
        'periods.html',
        client = client, years = view['years'], by_year = view['by_year'],
        period_months = PERIOD_MONTHS_HE, period_status_he= PERIOD_STATUS_HE, file_status_he= FILE_STATUS_HE,
        available_years= [current_year - 1, current_year, current_year + 1], current_year = current_year,)

@periods_bp.route('/periods')
def choose_client():
    """Client picker screen: entry point before viewing a specific client's periods."""
    clients = client_service.list_clients()
    return render_template('periods_picker.html', clients=clients)

@periods_bp.route('/periods/<int:client_id>/initialize', methods=['POST'])
def initialize_periods(client_id):
    """Create all 6 periods for a client for a given year, optionally skipping early ones."""
    try:
        year = int(request.form.get('year', 0))
        start_from = int(request.form.get('start_from_period', 1))
        created = period_service.initialize_periods_for_year(client_id, year, start_from)
        flash(f'נוצרו {len(created)} תקופות לשנת {year}', 'success')
    except ValueError as e:
        flash(str(e), 'error')
    return redirect(url_for('periods.periods', client_id=client_id))


@periods_bp.route('/periods/<int:client_id>/upload/<int:period_id>', methods=['POST'])
def upload_file(client_id, period_id):
    """
    Upload or replace the source file for a period.

    Two flows:
      - No existing file: create a new source_file record (upload_period_file).
      - Existing file (replace): delete existing meters/folders for this
        period, reset status to 'file_received', replace the file record,
        then delete the old physical file from disk.

    Note: steps in the replace flow are not wrapped in a single DB transaction
        if replace_period_file fails after meters/folders were already deleted, the period is left in a partial state. 
        Low risk in practice (see checklist), but a known limitation.
    """
    file= request.files.get('file')
    file_type = request.form.get('file_type', '').strip()

    if not file or not file.filename:
        flash('לא נבחר קובץ', 'error')
        return redirect(url_for('periods.periods', client_id=client_id))

    os.makedirs(UPLOAD_DIR, exist_ok=True)
    original_filename = file.filename
    stored_filename   = f"{uuid.uuid4().hex}_{secure_filename(original_filename)}"
    file_path         = os.path.join(UPLOAD_DIR, stored_filename)
    file.save(file_path)

    try:
        existing = source_file_service.get_period_source_file(period_id)
        if existing:
            old_file_path = existing.get('file_path') 

            meter_service.delete_meters_by_source_file(existing['source_file_id']) # שלב 1
            folder_service.delete_period_folders(period_id) # שלב 2
            period_service.update_status_manually(period_id, 'file_received') # שלב 3
            source_file_service.replace_period_file( period_id = period_id, original_filename = original_filename,
                file_type = file_type, stored_filename = stored_filename, file_path = file_path,) # שלב 4 : עלול לזרוק ValueError
            
            # remove old file data from disk
            if old_file_path and old_file_path != file_path and os.path.exists(old_file_path):
                try:
                    os.remove(old_file_path)
                except OSError:
                    pass

            flash(f'קובץ "{original_filename}" הוחלף בהצלחה - מונים ותיקים קודמים נמחקו', 'success')
        else:
            source_file_service.upload_period_file( period_id = period_id, original_filename = original_filename,
                file_type = file_type, stored_filename = stored_filename, file_path = file_path,)
            flash(f'קובץ "{original_filename}" הועלה בהצלחה', 'success')


    except ValueError as e:
        if os.path.exists(file_path):
            os.remove(file_path)
        flash(str(e), 'error')

    return redirect(url_for('periods.periods', client_id=client_id))


@periods_bp.route('/periods/<int:client_id>/process/<int:source_file_id>', methods=['POST'])
def process_file(client_id, source_file_id):
    """Trigger parsing of an uploaded source file into period_meters."""
    try:
        result = source_file_service.process_uploaded_file(source_file_id)
        rows   = result.get('rows_count') or 0

        summary = meter_service.get_period_status_summary(result['period_id'])
        missing = summary.get('missing_info', 0)

        if result['processing_status'] == 'success':
            msg = f'הקובץ עובד בהצלחה! {rows} מונים נטענו'
            if missing:
                msg += f', {missing} מונים עם מידע חסר (יש לבצע בדיקה)'
            flash(msg, 'success')
        elif result['processing_status'] == 'partial':
            msg = f'הקובץ עובד חלקית - {rows} מונים נטענו'
            if missing:
                msg += f', {missing} מונים עם מידע חסר (יש לבצע בדיקה)'
            flash(msg, 'error')
    except Exception as e:
        logger.exception(f"Failed processing source_file_id={source_file_id}")
        flash('שגיאה בעיבוד הקובץ; אנא וודא שהפורמט שנבחר תואם לקובץ שהועלה', 'error')
    return redirect(url_for('periods.periods', client_id=client_id))


@periods_bp.route('/periods/<int:client_id>/retry/<int:source_file_id>', methods=['POST'])
def retry_file(client_id, source_file_id):
    """Retry processing a source file that previously failed."""
    try:
        result = source_file_service.retry_processing(source_file_id)
        rows   = result.get('rows_count') or 0

        summary = meter_service.get_period_status_summary(result['period_id'])
        missing = summary.get('missing_info', 0)

        msg = f'הקובץ עובד מחדש - {rows} מונים נטענו'
        if missing:
            msg += f', {missing} מונים עם מידע חסר (יש לבצע בדיקה)'
        flash(msg, 'success')
    except Exception as e:
        logger.exception(f"Failed processing source_file_id={source_file_id}")
        flash('שגיאה בעיבוד הקובץ; אנא וודא שהפורמט שנבחר תואם לקובץ שהועלה', 'error')
    return redirect(url_for('periods.periods', client_id=client_id))


@periods_bp.route('/periods/<int:client_id>/skip/<int:period_id>', methods=['POST'])
def skip_period_route(client_id, period_id):
    """Mark a pending period as skipped (not relevant for this client)."""
    try:
        period_service.skip_period(period_id)
        flash('התקופה סומנה כדולגת', 'success')
    except ValueError as e:
        flash(str(e), 'error')
    return redirect(url_for('periods.periods', client_id=client_id))


@periods_bp.route('/periods/<int:client_id>/edit-status/<int:period_id>', methods=['POST'])
def edit_period_status(client_id, period_id):
    """Manually override a period's status (bypasses normal transition rules)."""
    new_status = request.form.get('status', '').strip()
    try:
        period = period_service.update_status_manually(period_id, new_status)
        flash(
            f'סטטוס תקופה {period["period_number"]}/{period["year"]} '
            f'עודכן ל"{PERIOD_STATUS_HE[new_status]}"',
            'success'
        )
    except ValueError as e:
        flash(str(e), 'error')
    return redirect(url_for('periods.periods', client_id=client_id))