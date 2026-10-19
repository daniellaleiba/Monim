"""
Mobile API blueprint - serves the reader's mobile app (WP3 contract). Returns JSON only.

reader_id in the URL is temporary, until authentication is decided.
The transmit endpoint (readings upload) will be added here later.
"""

import logging

from flask import Blueprint, jsonify

from routes.shared import mobile_service

mobile_api_bp = Blueprint('mobile_api', __name__)

logger = logging.getLogger(__name__)


@mobile_api_bp.route('/api/mobile/readers/<int:reader_id>/packages', methods=['GET'])
def download_packages(reader_id):
    """Download payload for the reader. Note: marks the returned folders as downloaded."""
    try:
        payload = mobile_service.get_download_payload(reader_id)
        return jsonify(payload), 200
    except ValueError as e:
        return jsonify({"error": str(e)}), 404
    except Exception:
        logger.exception("Mobile download failed for reader %s", reader_id)
        return jsonify({"error": "internal server error"}), 500
