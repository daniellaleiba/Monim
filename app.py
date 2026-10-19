"""
Monim - Water Meter Reading Management System
Flask application entry point.
ממשק ניהול קריאות מוני מים
"""

import logging
import os
from logging.handlers import RotatingFileHandler
from flask import Flask

def setup_logging():
    """
    Central logging configuration for Monim.
    Writes to both terminal and logs/monim.log.
    Level: WARNING and above (warning, error, critical).
    """
    # Create a logs folder if it does not exist.
    os.makedirs('logs', exist_ok=True)

    # Uniform format for all logos
    formatter = logging.Formatter(
        fmt='%(asctime)s %(levelname)-8s %(name)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S')

    # Handler 1: Terminal
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    # Handler 2: File - automatically rotates every 5MB, saves 3 files back
    file_handler = RotatingFileHandler('logs/monim.log', maxBytes=5_000_000, backupCount=3, encoding='utf-8')
    file_handler.setFormatter(formatter)

    # Set on the root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.WARNING)
    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)

setup_logging()

from routes.dashboard import dashboard_bp
from routes.clients import clients_bp
from routes.periods import periods_bp
from routes.meters import meters_bp
from routes.folders import folders_bp
from routes.readers import readers_bp
from routes.mobile_api import mobile_api_bp

app = Flask(__name__)

app.json.ensure_ascii = False  # Send Hebrew as UTF-8, not \uXXXX escapes
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'monim-dev-secret-key')

# Register blueprints
app.register_blueprint(dashboard_bp)
app.register_blueprint(clients_bp)
app.register_blueprint(periods_bp)
app.register_blueprint(meters_bp)
app.register_blueprint(folders_bp)
app.register_blueprint(readers_bp)
app.register_blueprint(mobile_api_bp)

if __name__ == '__main__':
    # debug=True + host='0.0.0.0' is fine for local development on a trusted network
    # NOT be used together in any real deployment
    app.run(debug=True, host='0.0.0.0', port=5000)