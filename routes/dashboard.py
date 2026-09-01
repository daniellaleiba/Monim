"""
Dashboard blueprint - מסך הבית של המערכת.
מציג KPI מרכזיים: תאגידים, תקופות, מונים, תיקים, קוראים, קריאות.
"""

from flask import Blueprint, render_template
from routes.shared import ( client_service, period_service, meter_service, folder_service, reader_service, reading_service)
from datetime import date

dashboard_bp = Blueprint('dashboard', __name__)

_HE_WEEKDAYS = { 0: 'שני', 1: 'שלישי', 2: 'רביעי', 3: 'חמישי',  4: 'שישי', 5: 'שבת', 6: 'ראשון',}

_HE_MONTHS = { 1: 'בינואר', 2: 'בפברואר', 3: 'במרץ', 4: 'באפריל',
    5: 'במאי', 6: 'ביוני', 7: 'ביולי', 8: 'באוגוסט', 9: 'בספטמבר', 10: 'באוקטובר', 11: 'בנובמבר', 12: 'בדצמבר', }

def _build_dashboard_view() -> dict:
    """
    Collects all KPI data from the services.
    Returns a dict with counts for the dashboard cards.

    Note: performance; this loops per-client and per-period (several separate queries per period: meters count, folders, readings). 
        Fine at current scale; if clients/periods grow significantly, worth replacing with aggregate SQL queries (similar to PeriodMeterService.get_status_summary).
    
    """
    # 1. סה"כ תאגידים
    clients = client_service.list_clients()
    total_clients = len(clients)

    # 2. תקופות + 3. מונים + 4. תיקים פתוחים + 6. קריאות מאושרות
    all_periods = []
    for client in clients:
        periods = period_service.list_client_periods(client['client_id'])
        all_periods.extend(periods)

    active_periods = [p for p in all_periods if p['status'] == 'active']
    total_active_periods = len(active_periods)

    # 3. סה"כ מונים בתקופות פעילות
    total_meters = 0
    for period in active_periods:
        total_meters += meter_service.count_period_meters(period['period_id'])

    # 4. תיקי עבודה פתוחים (pending / assigned / in_progress)  בכל התקופות הלא-סגורות
    open_statuses = ('pending', 'assigned', 'in_progress')
    active_period_statuses = ('file_received', 'active')
    total_open_folders = 0
    for period in all_periods:
        if period['status'] in active_period_statuses:
            folders = folder_service.get_period_folders(period['period_id'])
            total_open_folders += sum(1 for f in folders if f['status'] in open_statuses)

    # 5. קוראים פעילים
    active_readers = reader_service.list_readers(active_only=True)
    total_active_readers = len(active_readers)

    # 6. קריאות שאושרו בתקופות פעילות
    total_approved_readings = 0
    for period in active_periods:
        readings = reading_service.get_period_readings(period['period_id'])
        total_approved_readings += sum(
            1 for r in readings if r['reading_status'] == 'approved'
        )

    # לינקים לניווט: תאגיד ותקופה ראשונים אם קיימים
    first_client_id = clients[0]['client_id'] if clients else None
    first_active_period_id = active_periods[0]['period_id'] if active_periods else None

    return {
        'total_clients':total_clients,
        'total_active_periods':total_active_periods,
        'total_meters': total_meters,
        'total_open_folders': total_open_folders,
        'total_active_readers': total_active_readers,
        'total_approved_readings': total_approved_readings,
        'first_client_id': first_client_id,
        'first_active_period_id': first_active_period_id,
        'today_hebrew': _hebrew_today_string(),
    }

def _hebrew_today_string() -> str:
    """מחזיר תאריך היום בפורמט 'יום X, DD בחודש YYYY'."""
    today = date.today()
    weekday_name = _HE_WEEKDAYS[today.weekday()]
    month_name = _HE_MONTHS[today.month]
    return f'יום {weekday_name}, {today.day} {month_name} {today.year}'

@dashboard_bp.route('/')
def dashboard():
    data = _build_dashboard_view()
    return render_template('dashboard.html', **data)
