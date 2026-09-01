"""
Clients blueprint - manages client (water corporation) routes.
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash
from routes.shared import client_service

clients_bp = Blueprint('clients', __name__)


# מסך תאגידים
# ------------

@clients_bp.route('/clients')
def clients():
    """Main clients screen: full list of water corporations."""
    clients_list = client_service.list_clients()
    return render_template('clients.html', clients=clients_list)


@clients_bp.route('/clients/create', methods=['POST'])
def create_client():
    """Create a new client (water corporation)."""
    name               = request.form.get('name', '').strip()
    corporation_number = request.form.get('corporation_number', '').strip()
    city               = request.form.get('city', '').strip() or None
    try:
        client_service.create_client(name, corporation_number, city=city)
        flash(f'תאגיד "{name}" נוצר בהצלחה', 'success')
    except ValueError as e:
        flash(str(e), 'error')
    return redirect(url_for('clients.clients'))


@clients_bp.route('/clients/<int:client_id>/edit', methods=['POST'])
def edit_client(client_id):
    """Update a client's name, corporation number, and/or city."""
    name               = request.form.get('name', '').strip() or None
    corporation_number = request.form.get('corporation_number', '').strip() or None
    city               = request.form.get('city', '').strip() or None
    try:
        client_service.update_client(client_id, name=name, corporation_number=corporation_number, city=city)
        flash('התאגיד עודכן בהצלחה', 'success')
    except ValueError as e:
        flash(str(e), 'error')
    return redirect(url_for('clients.clients'))


@clients_bp.route('/clients/<int:client_id>/delete', methods=['POST'])
def delete_client(client_id):
    """
    Delete a client. 
    Blocked if the client has reading periods or folder templates, see ClientService.delete_client().
    """
    try:
        client = client_service.get_client(client_id)
        client_service.delete_client(client_id)
        flash(f'תאגיד "{client["name"]}" נמחק', 'success')
    except ValueError as e:
        flash(str(e), 'error')
    return redirect(url_for('clients.clients'))