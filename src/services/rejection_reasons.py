"""
Rejection reasons for readings transmitted from the mobile app (WP3 contract).

One list, used in both places that need it:
    - MobileService returns them when it rejects a reading
    - RejectedReadingService decides by them what is kept for the manager
The app receives them as the 'reason' of a rejected reading, so the values
themselves are part of the contract: do not rename them.
"""

METER_NOT_FOUND = 'meter_not_found'                            # No such meter in the period, and no new_meter
METER_NOT_IN_PACKAGE = 'meter_not_in_package'                  # The meter exists, but in another folder
METER_EXISTS_IN_OTHER_FOLDER = 'meter_exists_in_other_folder'  # A "new" meter that already exists in another folder
INVALID_DATA = 'invalid_data'                                  # The reading's data is invalid
MISSING_PHOTO = 'missing_photo'                                # has_photo, but no file arrived in the request
SERVER_ERROR = 'server_error'                                  # Unexpected failure on the server (logged)

# A retransmission alone will not fix these: they are kept for the manager.
# The others are temporary: the app sends the reading again, and it is accepted.
PERMANENT = (METER_NOT_FOUND, METER_NOT_IN_PACKAGE, METER_EXISTS_IN_OTHER_FOLDER, INVALID_DATA)