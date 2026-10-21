"""
Mobile API blueprint - serves the reader's mobile app (WP3 contract). Returns JSON only.

Two endpoints:
- Download: the reader's work packages (folders + meters).
- Transmit: readings (and their photos) sent back from the field for a package.

reader_id in the URL is temporary, until authentication is decided.
"""

import json
import logging

from flask import Blueprint, jsonify, request

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


@mobile_api_bp.route('/api/mobile/packages/<int:package_id>/readings', methods=['POST'])
def transmit_readings(package_id):
    """Transmit readings for a package. multipart/form-data: 'readings' (JSON list) + photo_<meter_number> files."""
    raw = request.form.get('readings')
    if raw is None:
        return jsonify({"error": "missing 'readings' field"}), 400
    try:
        readings = json.loads(raw)
    except ValueError:
        return jsonify({"error": "'readings' is not valid JSON"}), 400
    if not isinstance(readings, list):
        return jsonify({"error": "'readings' must be a JSON list"}), 400

    photos = request.files.to_dict()

    try:
        result = mobile_service.receive_readings(package_id, readings, photos)
        return jsonify(result), 200
    except ValueError as e:
        return jsonify({"error": str(e)}), 404
    except Exception:
        logger.exception("Mobile transmit failed for package %s", package_id)
        return jsonify({"error": "internal server error"}), 500
