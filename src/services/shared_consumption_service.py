"""
Shared Consumption Service - Business Logic Layer
    Calculates and saves shared water consumption per building.
    
    A building = one main meter (usage_type='1') + its apartments (usage_type='5')
    grouped by shared address.
    
    Shared consumption formula:
        (main_meter_consumption - sum(apartment_consumptions)) / apartment_count
    
    If result is negative → main meter marked as 'exception' for manual review.
"""

import logging
from typing import Optional
from src.repositories.periodmeter_repository import PeriodMeterRepository
from src.repositories.reading_period_repository import ReadingPeriodRepository
from src.services.periodmeter_service import PeriodMeterService 

logger = logging.getLogger(__name__)

class SharedConsumptionService:
    """
    Calculates shared water consumption for buildings in a period or folder.

    A building group = one main meter (usage_type='1') + apartments (usage_type='5')
    sharing the same meter_id prefix (building code).

    Responsibilities:
        - Group meters into buildings by meter_id prefix
        - Calculate shared consumption per building
        - Save results to shared_consumption field
        - Mark exceptions for manual review
    """

    def __init__(self):
        self.meter_repo = PeriodMeterRepository()
        self.period_repo = ReadingPeriodRepository()
        self.meter_service = PeriodMeterService()  
        self.BUILDING_KEY_LEN = 8  # ספציפי לפורמט נתניה: [4 רחוב][4 בניין]

    # --- VALIDATION:

    def _ensure_period_exists(self, period_id: int) -> dict:
        """Verify period exists and return it. Raises ValueError if not found."""
        period = self.period_repo.get_by_id(period_id)
        if not period:
            raise ValueError(f"תקופה {period_id} לא נמצאה במערכת")
        return period

    # --- GROUPING:

    def _build_groups(self, meters: list) -> list:
        """
        Group meters into buildings by meter_id prefix (first BUILDING_KEY_LEN digits).

        meter_id structure (Netanya): [4 digits street][4 digits building][3 digits unit]
        Grouping is by meter_id, NOT by address. Addresses are free text and
        unreliable: same address for different buildings (32 vs 32א), spelling
        variants (בלינסון/בילינסון), truncation at 20 chars.

        Returns: list of building dicts, only for buildings that have BOTH a main
                meter (usage_type '1') AND at least one apartment (usage_type '5'):
            {'building_key': str, 'address': str, 'main_meter': dict, 'apartments': list}
        """
        def _key(meter):
            mid = str((meter.get('raw_data') or {}).get('meter_id') or '')
            return mid[:self.BUILDING_KEY_LEN] if len(mid) >= self.BUILDING_KEY_LEN else None

        def _usage(meter):
            return str((meter.get('raw_data') or {}).get('usage_type', ''))

        by_building = {}

        # סבב ראשון: מונים כלליים (type 1) כל אחד פותח בניין
        for meter in meters:
            if _usage(meter) != '1':
                continue
            key = _key(meter)
            if not key:
                logger.warning(f"מונה כללי ללא meter_id תקין: {meter.get('meter_number')}")
                continue
            if key in by_building:
                logger.warning(
                    f"שני מונים כלליים לאותו בניין {key}: "
                    f"{by_building[key]['main_meter'].get('meter_number')} "
                    f"(כתובת: {by_building[key]['address']}) / "
                    f"{meter.get('meter_number')} (כתובת: {meter.get('address')})"
                )
                continue
            by_building[key] = {'building_key': key, 'address': meter.get('address') or '','main_meter': meter,'apartments':[],}

        # סבב שני: דירות (type 5) שיוך לבניין לפי אותה קידומת
        orphans = 0
        for meter in meters:
            if _usage(meter) != '5':
                continue
            key = _key(meter)
            if not key:
                continue
            if key in by_building:
                by_building[key]['apartments'].append(meter)
            else:
                orphans += 1
                logger.debug(f"דירה ללא מונה כללי: {(meter.get('raw_data') or {}).get('meter_id')} "
                    f"({meter.get('address')})")

        if orphans:
            logger.info(f"{orphans} דירות ללא מונה כללי, לא נכללו בחישוב")

        # בניין לחישוב = מונה כללי + לפחות דירה אחת
        groups = [g for g in by_building.values() if g['apartments']]
        logger.info(f"{len(by_building)} מונים כלליים → {len(groups)} בניינים לחישוב "
            f"({len(by_building) - len(groups)} ללא דירות)")
        return groups

    # --- CALCULATION:

    def _calculate_group(self, group: dict) -> Optional[float]:
        """
        Calculate shared consumption for a single building group.
        Formula: (main_consumption - sum(apartment_consumptions)) / apartment_count

        Note: apartments with no consumption value (no reading yet) are counted as 0 in the sum, not excluded. 
        This increases the computed shared value per apartment until all apartments have readings.

        Returns: shared consumption value, or None if calculation not possible
                    (missing consumption data on main meter or no apartments)
        """
        main = group['main_meter']
        apartments = group['apartments']

        if not apartments:
            return None

        main_consumption = main.get('consumption')
        if main_consumption is None:
            return None

        # סכום צריכת הדירות  דירות ללא קריאה נספרות כ-0
        apt_sum = sum( float(a['consumption']) for a in apartments if a.get('consumption') is not None)

        apt_count = len(apartments)
        shared = (float(main_consumption) - apt_sum) / apt_count
        return round(shared, 3)

    # --- MAIN:

    def calculate(self, period_id: int, folder_id: int = None, include_details: bool = False) -> dict:
        """
        Calculate and save shared consumption for all buildings in a period/folder.

        Flow:
            1. Fetch all relevant meters (usage_type 1 and 5)
            2. Group into buildings by meter_id prefix
            3. For each building:
                a. If the main meter is currently 'exception' with manager_notes that match exactly what this method writes on negative-consumption
                    exceptions (see below), reset it back to 'new', self-healing a previous run's exception, without touching manually-set exceptions.
                b. Reset shared_consumption to NULL (clean state)
                c. Calculate shared value
                d. If negative → mark main meter as exception, with a manager_notes message this method later matches on step (a) to auto-reset it
                d. If valid → save to all apartments
                
        Note: apartments with no matching main meter ("orphans") are logged but not counted anywhere in the returned summary.

        Args:
            period_id: Reading period ID
            folder_id: Optional, restrict to a specific folder
            include_details: If True, also return per-building details for skipped and exception buildings (address + reason). 
            Defaults to False to keep the response lightweight for callers (e.g. the JSON API route) that only need the summary counts.

        Returns: summary dict:
            {
                'buildings': int,       # כמה בניינים עובדו
                'apartments_updated': int,  # כמה דירות עודכנו
                'exceptions': int,      # כמה בניינים חריגים
                'skipped': int,         # כמה בניינים דולגו (אין נתונים)

                # Only present when include_details=True:
                'skipped_details': list[dict],    # [{'address': str, 'reason': str}, ...]
                'exception_details': list[dict],  # [{'address': str, 'shared_consumption': float}, ...]
            }
        """
        self._ensure_period_exists(period_id)

        # שלב 1: שליפה
        meters = self.meter_repo.list_meters_for_shared_consumption(period_id, folder_id)
        if not meters:
            return {'buildings': 0, 'apartments_updated': 0, 'exceptions': 0, 'skipped': 0}

        # שלב 2: קיבוץ
        groups = self._build_groups(meters)

        buildings, apts_updated, exceptions, skipped = 0, 0, 0, 0
        skipped_details = [] if include_details else None
        exception_details = [] if include_details else None

        for group in groups:
            buildings += 1
            main       = group['main_meter']
            apartments = group['apartments']
            address      = group['address']
            building_key = group['building_key']


            # איפוס exception ישן מצריכה משותפת - רק אם נוצר על ידינו
            if (main.get('work_status') == 'exception' and 
                main.get('manager_notes') and 
                'צריכה משותפת שלילית' in main.get('manager_notes', '')):
                self.meter_service.update_work_status(main['period_meter_id'], 'new')
                self.meter_service.apply_reading_to_current_state(main['period_meter_id'], manager_notes='')

            # שלב 3א: איפוס
            self.meter_service.reset_shared_consumption_by_prefix(period_id, building_key)

            # שלב 3ב: חישוב
            shared = self._calculate_group(group)

            if shared is None:
                # אין נתוני קריאה ,  דלג
                skipped += 1
                if include_details:
                    skipped_details.append({'address': address, 'reason': 'חסרים נתוני צריכה'})
                logger.debug(f"דולג בניין בכתובת '{address}'; חסרים נתוני צריכה")
                continue

            if shared < 0:
                # שלב 3ג: חריג
                exceptions += 1
                if include_details:
                    exception_details.append({'address': address, 'shared_consumption': shared})
                self.meter_service.mark_exception( main['period_meter_id'], None,
                    notes=f"צריכה משותפת שלילית ({shared}) ;נדרשת ביקורת")
                logger.warning(f"צריכה משותפת שלילית בכתובת '{address}': {shared}")
                continue

            # שלב 3ד: שמירה על הדירות
            updates = [
                 {'period_meter_id': a['period_meter_id'], 'shared_consumption': shared}
                for a in apartments ]
            self.meter_service.bulk_update_shared_consumption(updates)
            apts_updated += len(updates)

        result = { 'buildings': buildings, 'apartments_updated': apts_updated, 'exceptions': exceptions, 'skipped': skipped,}
        if include_details:
            result['skipped_details'] = skipped_details
            result['exception_details'] = exception_details
        return result