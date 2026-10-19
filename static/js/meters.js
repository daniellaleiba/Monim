/**
 * Meters screen: client-side logic for templates/meters.html.
 *
 * Handles: filtering/search, virtual-scroll rendering of the meters table
 * (for performance with large meter lists), the meter detail/edit modal,
 * and manager actions (estimate, bulk-estimate, shared-consumption, save).
 *
 * Expects the following globals to already be defined by inline <script>
 * blocks in meters.html, BEFORE this file loads:
 *   - ALL_METERS  : Array of meter row objects (from meters_json)
 *   - STATUS_HE   : {work_status: Hebrew label}
 *   - FAULT_CODES : {code: Hebrew description}
 *   - CLIENT_CITY : string, used to build Google Maps links
 *   - prefilterFolderId : number|null, folder_id to pre-filter by
 *   - window.PERIOD_ID : current period_id, used in API calls
 *   - window.PREFILTER_FOLDER_ID : folder_id passed to bulk-estimate/shared-consumption
 */

let currentFilter        = 'all';
let currentSearch        = '';
let currentFolderFilter  = null;  // מסנן לפי תיק (מהפניה ממסך תיקים)
let currentWorkStatusFilter = '';
let currentFaultCodeFilter  = '';

// --- סינון וחיפוש ---

function setFilter(status, cardEl) {
    currentFilter = status;
    document.querySelectorAll('.summary-card').forEach(c => c.classList.remove('active-filter'));
    if (cardEl) cardEl.classList.add('active-filter');
    renderVirtualScroll();
}

function onSearch(val) {
    currentSearch = val;
    renderVirtualScroll();
}

function onFilterChange() {
    currentWorkStatusFilter = document.getElementById('filter-work-status').value;
    renderVirtualScroll();
}

function onFaultCodeFilter(val) {
    currentFaultCodeFilter = val;
    renderVirtualScroll();
}

function getFiltered() {
    const term = currentSearch.trim().toLowerCase();
    return ALL_METERS.filter(m => {
        const statusOk      = currentFilter === 'all' || m.work_status === currentFilter;
        const folderOk      = !currentFolderFilter || m.folder_id === currentFolderFilter;
        const searchOk      = !term ||
            String(m.meter_number   || '').toLowerCase().includes(term) ||
            String(m.customer_number|| '').toLowerCase().includes(term) ||
            (() => {
                const addr = String(m.address || '').toLowerCase();
                const parts = term.trim().split(/\s+/);

                // If term ends with a number, treat it as a building search
                const lastPart = parts[parts.length - 1];
                if (parts.length >= 2 && /^\d+$/.test(lastPart)) {
                    const street = parts.slice(0, -1).join(' ');
                    const building = lastPart;
                    if (!addr.includes(street)) return false;
                    // Match exact building: either end of string, or followed by '/' (apartments: "1/18")
                    const afterStreet = addr.slice(addr.indexOf(street) + street.length).trim();
                    // Main meter: exactly the building number
                    if (afterStreet === building) return true;
                    // Apartment: "digit(s)/building" building appears after the slash
                    if (afterStreet.match(new RegExp('^\\d+\\/' + building + '$'))) return true;
                    return false;
                }

                // Default: simple includes search
                return addr.includes(term);
            })() ||
            (m.raw_data?.meter_id   || '').toLowerCase().includes(term);
        const workStatusOk  = !currentWorkStatusFilter  || m.work_status === currentWorkStatusFilter;
        const faultCodeOk  = !currentFaultCodeFilter ||
                             m.current_fault_code === currentFaultCodeFilter;
        return statusOk && folderOk && searchOk && workStatusOk && faultCodeOk;
    });
}

// --- Virtual Scroll ---

const STATUS_ROW_CLASS = {
    'completed':    'row-completed',
    'exception':    'row-exception',
    'missing_info': 'row-missing_info',
    'in_progress':  'row-in_progress',
};

const BUFFER      = 5;      // שורות buffer מעל ומתחת לאזור הנראה
let   ROW_HEIGHT  = 33;     // גובה שורה בפיקסלים - נמדד אחרי הרינדור הראשון
let   filteredRows = [];
let   currentMeterIndex = -1;
let   rafPending  = false;

// מחשב ומגדיר את גובה אזור הגלילה
function setViewportHeight() {
    const vp  = document.getElementById('vs-viewport');
    const top = vp.getBoundingClientRect().top;
    vp.style.height = Math.max(720, window.innerHeight - top - 20) + 'px';
}

// מודד את גובה השורה האמיתי אחרי הרינדור הראשון
function measureRowHeight() {
    const row = document.querySelector('#vs-tbody tr.meter-row');
    if (!row) return;
    const h = row.getBoundingClientRect().height;
    if (h > 0 && Math.abs(h - ROW_HEIGHT) > 2) {
        ROW_HEIGHT = h;
        _paintRows();
    }
}

// רינדור ראשי - מאפסים scroll ומציירים מחדש
function renderVirtualScroll() {
    filteredRows = getFiltered();

    document.getElementById('results-count').textContent =
        `${filteredRows.length} מונים${filteredRows.length !== ALL_METERS.length ? ' (מסונן)' : ''}`;

    const vp = document.getElementById('vs-viewport');
    vp.scrollTop = 0;
    _paintRows();
}

// מציייר רק את השורות הנראות + buffer
function _paintRows() {
    const vp        = document.getElementById('vs-viewport');
    const tbody     = document.getElementById('vs-tbody');
    const scrollTop = vp.scrollTop;
    const vpHeight  = vp.clientHeight;
    const total     = filteredRows.length;

    if (total === 0) {
        tbody.innerHTML = '<tr><td colspan="19" style="text-align:center;padding:40px;color:var(--gray-500);">לא נמצאו מונים</td></tr>';
        return;
    }

    const startIdx = Math.max(0, Math.floor(scrollTop / ROW_HEIGHT) - BUFFER);
    const endIdx   = Math.min(total, Math.ceil((scrollTop + vpHeight) / ROW_HEIGHT) + BUFFER);
    const topPad   = startIdx * ROW_HEIGHT;
    const botPad   = Math.max(0, (total - endIdx) * ROW_HEIGHT);

    let html = '';

    if (topPad > 0) {
        html += `<tr style="height:${topPad}px;line-height:0;"><td colspan="19" style="height:${topPad}px;padding:0;border:0;font-size:0;"></td></tr>`;
    }

    for (let i = startIdx; i < endIdx; i++) {
        const m           = filteredRows[i];        
        const rowClass    = STATUS_ROW_CLASS[m.work_status] || '';  
        const statusLabel = STATUS_HE[m.work_status] || m.work_status || '-'; 
        const statusClass = `badge-status-${m.work_status}`;    
        
        const raw          = m.raw_data || {};
        const meterId      = raw.meter_id || '-';
        const readingTime  = m.reading_time || null;
        const dateStr      = readingTime ? readingTime.substring(0, 10) : '-';
        const timeStr      = readingTime && readingTime.length >= 16 ? readingTime.substring(11, 16) : '-';
        const faultLabel   = m.current_fault_code
                            ? `${m.current_fault_code} - ${FAULT_CODES[m.current_fault_code] || ''}`: '-';
        const estimateMark = m.is_estimated ? '✓' : '';
        const customerName = m.customer_name || '-';

        html += `<tr class="${rowClass} meter-row" data-meter-id="${m.period_meter_id}" title="לחץ לפרטים">
            <td style="text-align:center;color:var(--gray-500);font-size:12px;">${i + 1}</td>
            <td style="font-size:13px;color:var(--gray-500);">${esc(meterId)}</td>
            <td><strong>${esc(m.meter_number)}</strong></td>
            <td>${esc(m.customer_number)}</td>
            <td style="max-width:110px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${esc(customerName)}</td>
            <td style="white-space:nowrap;">${esc(m.address)}</td>
            <td style="direction:ltr;text-align:right;white-space:nowrap;">${m.walk_order ?? '-'}</td>
            <td style="direction:ltr;text-align:right;">${fmtNum(m.previous_reading)}</td>
            <td>-</td>
            <td style="direction:ltr;text-align:right;white-space:nowrap;">${fmtNum(m.current_reading)}</td>
            <td style="direction:ltr;text-align:right;white-space:nowrap;">${fmtNum(m.consumption)}</td>
            <td style="direction:ltr;text-align:right;white-space:nowrap;">${m.shared_consumption != null ? fmtNum(m.shared_consumption) : '-'}</td>
            <td style="direction:ltr;text-align:right;">${fmtNum(m.addon)}</td>
            <td style="text-align:center;white-space:nowrap;">${estimateMark}</td>
            <td style="font-size:13px;max-width:140px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${faultLabel}</td>
            <td style="direction:ltr;font-size:13px;white-space:nowrap;min-width:90px;">${dateStr}</td>
            <td style="direction:ltr;font-size:13px;white-space:nowrap;">${timeStr}</td>
            <td style="white-space:nowrap;"><span class="badge ${statusClass}">${statusLabel}</span></td>
            <td style="white-space:nowrap;font-size:13px;color:var(--gray-600);">${esc(m.folder_name)}</td>
        </tr>`;
    }

    if (botPad > 0) {
        html += `<tr style="height:${botPad}px;line-height:0;"><td colspan="19" style="height:${botPad}px;padding:0;border:0;font-size:0;"></td></tr>`;
    }

    tbody.innerHTML = html;
}

// גלילה - מצייר מחדש עם throttle של requestAnimationFrame
document.getElementById('vs-viewport').addEventListener('scroll', () => {
    if (rafPending) return;
    rafPending = true;
    requestAnimationFrame(() => {
        _paintRows();
        rafPending = false;
    });
}, { passive: true });

// לחיצה על שורה - event delegation (השורות נהרסות ונוצרות בגלילה)
document.getElementById('vs-viewport').addEventListener('click', e => {
    const row = e.target.closest('tr[data-meter-id]');
    if (row) openMeterModal(Number(row.dataset.meterId));
});

function esc(v) {
    if (v === null || v === undefined) return '-';
    return String(v)
        .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function fmtNum(v) {
    if (v == null) return '-';
    return parseFloat(parseFloat(v).toFixed(2)).toString();
}

// --- Modal ---

function navigateMeter(direction) {
    const newIndex = currentMeterIndex + direction;
    if (newIndex < 0 || newIndex >= filteredRows.length) return;
    const nextMeter = filteredRows[newIndex];
    openMeterModal(nextMeter.period_meter_id);
    document.getElementById('btn-prev-meter').disabled = (newIndex <= 0);
    document.getElementById('btn-next-meter').disabled = (newIndex >= filteredRows.length - 1);
}

/**
 * Populate and open the meter detail/edit modal for a given meter.
 * Resets transient UI state (addon row, photo preview) before filling in
 * all fields from ALL_METERS + raw_data.
 */
function openMeterModal(period_meter_id) {
    const m = ALL_METERS.find(x => x.period_meter_id === period_meter_id);
    if (!m) return;
    const raw = m.raw_data || {};

    const successMsg = document.getElementById('save-success-msg');
    if (successMsg) successMsg.style.display = 'none';

    // איפוס השדה "תוספת"
    const addonRow = document.getElementById('mf-addon-row');
    if (addonRow) addonRow.style.display = 'none';
    document.getElementById('mf-addon-value').textContent = '-';
    document.getElementById('field-data-content').dataset.isEstimated = 'false';

    // איפוס תמונה 
    document.getElementById('meter-photo-preview').style.display = 'none';
    document.querySelector('.meter-photo-placeholder').style.display = 'flex';
    document.getElementById('meter-photo-input').value = '';

    // --- Header ---
    document.getElementById('modal-meter-title').textContent = `מונה ${m.meter_number}`;
    const estimatedBadge = document.getElementById('modal-estimated-badge');
    if (estimatedBadge) {
        estimatedBadge.style.display = m.is_estimated ? 'inline-flex' : 'none';
    }
    
    setEstimateButtonState(m.is_estimated);

    const badge = document.getElementById('modal-status-badge');
    badge.textContent = STATUS_HE[m.work_status] || m.work_status || '-';
    badge.className = `status-badge-lg badge-status-${m.work_status}`;

    // --- כתובת + GPS ---
    const mapsQuery = m.address
        ? (CLIENT_CITY ? encodeURIComponent(m.address + ', ' + CLIENT_CITY) : encodeURIComponent(m.address))
        : null;
    const mapsLink = mapsQuery
        ? `<a href="https://www.google.com/maps/search/?api=1&query=${mapsQuery}" target="_blank"
              title="פתח במפות גוגל" style="vertical-align:middle;">
              <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24"
                   fill="none" stroke="#2563eb" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/>
                  <circle cx="12" cy="10" r="3"/>
              </svg>
           </a>`
        : '';

    const cardName = document.getElementById('mf-customer-card-name');
    const cardAddr = document.getElementById('mf-customer-card-address');
    const cardMaps = document.getElementById('mf-customer-card-maps');
    if (cardName) cardName.textContent = m.customer_name || '';
    if (cardAddr) cardAddr.textContent = m.address       || '';
    if (cardMaps) cardMaps.innerHTML   = mapsLink;

    // --- זיהוי ---
    document.getElementById('mf-meter-number').textContent    = m.meter_number    || '-';
    document.getElementById('mf-customer-number').textContent = m.customer_number || '-';
    document.getElementById('mf-meter-id').textContent        = raw.meter_id        || '-';
    document.getElementById('mf-physical').textContent        = raw.physical_number || '-';
    document.getElementById('mf-walk-order').textContent      = m.walk_order       || '-';
    document.getElementById('mf-install-date').textContent    = raw.install_date_alt || '-';
    document.getElementById('mf-reception-date').textContent  = raw.reception_date  || '-';
    document.getElementById('mf-location').textContent        = raw.meter_location  || '-';
    document.getElementById('mf-usage-type').textContent = raw.usage_type || '-';

    // --- עבודה ---
    const folderHeader = document.getElementById('mf-folder-header');
    const folderVal    = document.getElementById('mf-folder-header-val');
    if (m.folder_name) {
        folderVal.textContent = m.folder_name;
        folderHeader.style.display = 'block';
    } else {
        folderHeader.style.display = 'none';
    }
    document.getElementById('mf-prev-reading').textContent  = m.previous_reading != null ? m.previous_reading : '-';
    const currEl = document.getElementById('mf-curr-reading');
    if (currEl) currEl.value = m.current_reading != null ? m.current_reading : '';
    updateDiff(m.previous_reading, m.current_reading);

    // --- סטטוס + תאור ---
    const currentCode = m.current_fault_code || '';
    const faultInput  = document.getElementById('mf-fault-code-input');
    const faultSel    = document.getElementById('mf-fault-code-select');
    const faultSelSts = document.getElementById('mf-fault-code-input-sel');
    if (faultInput)  faultInput.value  = currentCode;
    if (faultSel)    faultSel.value    = currentCode;
    if (faultSelSts) faultSelSts.value = currentCode;

    // --- נתוני קריאה בשטח ---
    const readingDate      = document.getElementById('mf-reading-date');
    const transmissionDate = document.getElementById('mf-transmission-date');
    const readingTime      = document.getElementById('mf-reading-time');
    const addonEl          = document.getElementById('mf-addon');
    const fieldNotes       = document.getElementById('mf-field-notes');

    // ת. קריאה  מתוך reading_time (אם קיים)
    if (readingDate) {
        const rt = m.reading_time || raw.reading_date || null;
        readingDate.value = rt ? rt.substring(0, 10) : '';
    }
    // ת. שידור  מתוך transmitted_at (אם קיים)
    if (transmissionDate) {
        const ta = m.transmitted_at || raw.transmitted_at || null;
        transmissionDate.value = ta ? ta.substring(0, 10) : '';
    }
    // שעה
    if (readingTime) {
        const rt = m.reading_time || null;
        readingTime.value = rt ? rt.substring(11, 16) : '';
    }
    if (addonEl)    addonEl.textContent    = raw.addon    || '-';
    if (fieldNotes) fieldNotes.value = m.field_notes || '';

    // שמירת ה-period_meter_id לשימוש בשמירת תאריכים
    document.getElementById('field-data-content').dataset.meterId = period_meter_id;

    // --- קריאות קודמות ---
    const histReadings = (raw.hist_readings || []).slice(1); // ק.1 עד ק.6
    const histDiffs    = raw.hist_diffs     || [];
    const tbody = document.getElementById('modal-hist-tbody');
    if (histReadings.length > 0 && histReadings.some(v => v && v !== 0)) {
        const labels = ['ק.1 (אחרונה)', 'ק.2', 'ק.3', 'ק.4', 'ק.5', 'ק.6 (שנה שעברה)'];
        tbody.innerHTML = histReadings.map((reading, i) => {
        let diff;
        if (i === 0) {
            // ק.1: הפרש בין הקריאה הנוכחית לק.1
            const current = (raw.hist_readings || [])[0];
            diff = (current != null && reading != null) ? (current - reading).toFixed(1) : '-';
        } else {
            // ק.2 עד ק.6: הפרש מגיע מהקובץ, אינדקס מוזז ב-1
            diff = histDiffs[i - 1] != null ? histDiffs[i - 1] : '-';
        }
        const isParallel = i === 5;
            return `<tr class="${isParallel ? 'hist-parallel' : ''}">
                <td>${labels[i]}</td>
                <td>${reading != null && reading !== 0 ? reading : '-'}</td>
                <td>${diff !== '-' && diff !== 0 ? diff : '-'}</td>
            </tr>`;
        }).join('');
    } else {
        tbody.innerHTML = '<tr><td colspan="3" style="text-align:center;color:var(--gray-400);">אין נתוני היסטוריה</td></tr>';
    }

    // --- שדות חסרים ---
    const missingSection = document.getElementById('modal-missing-section');
    const missing = raw.missing_fields || [];
    if (missing.length > 0) {
        document.getElementById('modal-missing-fields').textContent = missing.join(', ');
        missingSection.style.display = 'block';
    } else {
        missingSection.style.display = 'none';
    }

    // --- הערות ---
    document.getElementById('mf-manager-notes').value = m.manager_notes || '';

    // --- סטטוס ---
    const sel = document.getElementById('modal-status-select');
    for (const opt of sel.options) opt.selected = opt.value === m.work_status;

    currentMeterIndex = filteredRows.findIndex(m => m.period_meter_id === period_meter_id);
    const btnPrev = document.getElementById('btn-prev-meter');
    const btnNext = document.getElementById('btn-next-meter');
    if (btnPrev) btnPrev.disabled = (currentMeterIndex <= 0);
    if (btnNext) btnNext.disabled = (currentMeterIndex >= filteredRows.length - 1);

    openModal('modal-meter');
}

// --- הרצה ראשונית ---
document.addEventListener('DOMContentLoaded', () => {
    // מלא dropdowns של קודי תקלות פעם אחת בלבד
    const faultSel = document.getElementById('mf-fault-code-select');
    if (faultSel && Object.keys(FAULT_CODES).length > 0) {
        Object.entries(FAULT_CODES).forEach(([code, desc]) => {
            const opt = document.createElement('option');
            opt.value = code;
            opt.textContent = `${code} - ${desc}`;
            faultSel.appendChild(opt);
        });
    }
    // פילטר תיק מוקדם (כשמגיעים ממסך תיקים)
    const inFolderCtx       = !!document.getElementById('js-folder-ctx');
    if (prefilterFolderId) {
        currentFolderFilter = prefilterFolderId;
        if (!inFolderCtx) {
            const bar = document.createElement('div');
            bar.className = 'folder-filter-bar';
            bar.innerHTML = `מוצגים מונים מתיק מסוים בלבד
                <button onclick="clearFolderFilter()" style="margin-right:12px;background:none;border:1px solid currentColor;
                border-radius:4px;padding:2px 8px;cursor:pointer;font-size:12px;">הצג הכל</button>`;
            document.querySelector('.search-bar').before(bar);
        }
    }

    // Populate work status dropdown
    const workStatuses = [...new Set(ALL_METERS.map(m => m.work_status).filter(Boolean))];
    const workSel = document.getElementById('filter-work-status');
    workStatuses.forEach(s => {
        const opt = document.createElement('option');
        opt.value = s;
        opt.textContent = STATUS_HE[s] || s;
        workSel.appendChild(opt);
    });

    // Populate fault code dropdown
    const fcSelect = document.getElementById('filter-fault-code');
    Object.entries(FAULT_CODES).forEach(([code, desc]) => {
        const opt = document.createElement('option');
        opt.value = code;
        opt.textContent = desc;
        fcSelect.appendChild(opt);
    });

    setViewportHeight();
    renderVirtualScroll();

    // מדידת גובה שורה אמיתי אחרי הרינדור הראשון
    requestAnimationFrame(measureRowHeight);

    window.addEventListener('resize', () => {
        setViewportHeight();
        _paintRows();
    });

    document.getElementById('mf-curr-reading').addEventListener('input', function() {
        const prev = parseFloat(document.getElementById('mf-prev-reading').textContent);
        updateDiff(prev, parseFloat(this.value));
    });
});

function updateDiff(prev, curr) {
    const diffEl = document.getElementById('mf-diff-reading');
    if (!diffEl) return;
    if (curr != null && prev != null && !isNaN(curr) && !isNaN(prev)) {
        const diff = fmtNum(parseFloat(curr) - parseFloat(prev));
        const arrow = diff >= 0 ? '↑' : '↓';
        diffEl.textContent = (diff > 0 ? '+' : '') + diff + ' ' + arrow;
        diffEl.style.color = diff >= 0 ? '#16a34a' : '#dc2626';
    } else {
        diffEl.textContent = '-';
        diffEl.style.color = 'var(--gray-400)';
    }
}


function setEstimateButtonState(isEstimated) {
    // helper func
    const btn = document.getElementById('btn-estimate');
    if (!btn) return;
    if (isEstimated) {
        btn.textContent = '✓ הערכה בוצעה';
        btn.style.background = '#16a34a';
        btn.style.color = 'white';
        btn.style.borderColor = '#16a34a';
    } else {
        btn.textContent = ' ביצוע הערכה';
        btn.style.background = '';
        btn.style.color = '';
        btn.style.borderColor = '';
    }
}

async function apiFetch(url, options) {
    try {
        const res = await fetch(url, options);
        return await res.json();
    } catch (e) {
        alert('שגיאת תקשורת עם השרת');
        return null;
    }
}

function setButtonSpinner(button, loadingText) {
    button.disabled = true;
    button.innerHTML = `<span class="btn-spinner"></span> ${loadingText}`;
}

function restoreButton(button, originalHTML) {
    button.disabled = false;
    button.innerHTML = originalHTML;
}

async function doEstimate() {
    const meterId = Number(document.getElementById('field-data-content').dataset.meterId);
    const faultCode = document.getElementById('mf-fault-code-input').value.trim();
    if (!faultCode) {
        alert('לא ניתן לבצע הערכה ללא קוד תקלה');
        return;
    }

    const data = await apiFetch(`/meters/${meterId}/estimate?fault_code=${faultCode}`);
    if (!data) return;

    if (!data.ok) {
        alert(data.error || 'שגיאה בחישוב הערכה');
        return;
    }

    document.getElementById('mf-curr-reading').value = data.current_reading;
    const addonRow = document.getElementById('mf-addon-row');
    // עדכון התוספת למסך
    const addonEl  = document.getElementById('mf-addon-value');
    if (data.is_stopped_meter && data.addon != null) {
        addonEl.textContent = data.addon;
        addonRow.style.display = 'flex';
    } else {
        addonEl.textContent = '-';
        addonRow.style.display = 'none';
    }
    updateDiff(data.previous_reading, data.current_reading);
    document.getElementById('field-data-content').dataset.isEstimated = 'true';
    const estimatedBadge = document.getElementById('modal-estimated-badge');
    if (estimatedBadge) estimatedBadge.style.display = 'inline-flex';
    
    setEstimateButtonState(true);

}

async function doBulkEstimate() {
    const candidates = ALL_METERS.filter(m =>
        m.current_fault_code &&
        m.current_fault_code !== '1' &&
        !m.is_estimated &&
        m.raw_data?.hist_readings
    );

    if (candidates.length === 0) {
        alert('לא נמצאו מונים לביצוע הערכה כוללת');
        return;
    }

    if (!confirm(`נמצאו ${candidates.length} מונים. האם לבצע הערכה כוללת?`)) return;

    const button = document.getElementById('btn-bulk-estimate');
    setButtonSpinner(button, 'מחשב...');

    const data = await apiFetch(`/meters/${window.PERIOD_ID}/bulk-estimate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ folder_id: window.PREFILTER_FOLDER_ID || null }),
    });
    if (data){
        if (data.ok) {
            (data.updates || []).forEach(u => {
                const idx = ALL_METERS.findIndex(x => x.period_meter_id === u.period_meter_id);
                if (idx !== -1) {
                    ALL_METERS[idx].is_estimated    = true;
                    ALL_METERS[idx].current_reading = u.current_reading;
                    ALL_METERS[idx].consumption     = u.consumption;
                }
            });
            renderVirtualScroll();
            alert(`הערכה בוצעה על ${data.estimated} מונים`);
        } else {
            alert('שגיאה: ' + (data.error || 'שגיאה לא ידועה'));
        }
    }

    restoreButton(button, 'הערכה כוללת');

}

async function doSharedConsumption() {
    if (!confirm('האם לחשב צריכה משותפת?')) return;

    const button = document.querySelector('[onclick="doSharedConsumption()"]');
    setButtonSpinner(button, 'מחשב...');

    const data = await apiFetch(`/meters/${window.PERIOD_ID}/shared-consumption`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ folder_id: window.PREFILTER_FOLDER_ID || null }),
    });
    if (data) {
        if (data.ok) {
            let msg = `צריכה משותפת חושבה עבור ${data.buildings} בניינים, ${data.apartments_updated} דירות עודכנו`;
            if (data.exceptions > 0) {
                msg += `\n${data.exceptions} בניינים חריגים; נדרשת ביקורת`;
            }
            alert(msg);
            location.reload();
        } else {
            alert('שגיאה: ' + (data.error || 'שגיאה לא ידועה')); }
    }
    
    restoreButton(button, '🏢 צריכה משותפת');
}

function toggleModalFullscreen() {
    const modal = document.getElementById('modal-meter');
    const btn   = document.getElementById('btn-expand-modal');
    const isFullscreen = modal.classList.toggle('modal-fullscreen');
    btn.textContent = isFullscreen ? '⊡' : '⛶';
}

function clearFolderFilter() {
    currentFolderFilter = null;
    document.querySelector('.folder-filter-bar')?.remove();
    renderVirtualScroll();
}

function onFaultDescSelect(code) {
    const input = document.getElementById('mf-fault-code-input');
    if (input) input.value = code;
}
function onFaultCodeInput(code) {
    const sel = document.getElementById('mf-fault-code-select');
    if (!sel) return;
    const exists = Array.from(sel.options).some(o => o.value === code.trim());
    sel.value = exists ? code.trim() : '';
}

async function saveMeterChanges() {
    const meterId = Number(document.getElementById('field-data-content').dataset.meterId);

    const currVal     = document.getElementById('mf-curr-reading').value;
    const readingDate = document.getElementById('mf-reading-date').value;
    const readingTime = document.getElementById('mf-reading-time').value;

    const payload = {
        current_reading : currVal !== '' ? parseFloat(currVal) : null,
        work_status     : document.getElementById('modal-status-select').value || null,
        fault_code      : document.getElementById('mf-fault-code-input').value.trim() || null,
        manager_notes   : document.getElementById('mf-manager-notes').value.trim() || null,
        addon: (() => {
                const v = document.getElementById('mf-addon-value').textContent.trim();
                const n = parseFloat(v);
                return isNaN(n) ? null : n;
            })(),
        reading_time    : (readingDate && readingTime)
                            ? readingDate + 'T' + readingTime + ':00'
                            : readingDate ? readingDate + 'T00:00:00' : null,
        is_estimated    : document.getElementById('field-data-content').dataset.isEstimated === 'true',
    };

    const data = await apiFetch(`/meters/${meterId}/update-manager`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
    });
    if (!data) return;

    if (data.ok) {
        if (data.ok) {
            // עדכון ALL_METERS מקומית כדי שהמונה יציג נתונים נכונים בפתיחה הבאה
            const idx = ALL_METERS.findIndex(x => x.period_meter_id === meterId);
            if (idx !== -1) {
                if (payload.current_reading != null) {
                    ALL_METERS[idx].current_reading = payload.current_reading;
                    if (data.consumption != null) {
                        ALL_METERS[idx].consumption = data.consumption;
                    }
                }
                if (data.work_status)                    ALL_METERS[idx].work_status        = data.work_status;
                if (payload.fault_code !== undefined)   ALL_METERS[idx].current_fault_code = payload.fault_code;
                if (payload.manager_notes !== undefined) ALL_METERS[idx].manager_notes     = payload.manager_notes;
                if (payload.addon != null)               ALL_METERS[idx].addon             = payload.addon;
                if (payload.reading_time != null)        ALL_METERS[idx].reading_time      = payload.reading_time;
                if (payload.is_estimated)                ALL_METERS[idx].is_estimated      = true;
            }
            renderVirtualScroll();
            const successMsg = document.getElementById('save-success-msg');
            if (successMsg) {
                successMsg.style.display = 'inline';
                setTimeout(() => { successMsg.style.display = 'none'; }, 3000);
            }
        } else {
            alert('שגיאה: ' + (data.error || 'שגיאה לא ידועה'));
        }
    }
}

function closeMeterModal() {
    document.getElementById('modal-meter').style.display = 'none';
    document.getElementById('modal-meter').classList.remove('modal-fullscreen');
    document.getElementById('btn-expand-modal').textContent = '⛶';
    document.getElementById('modal-overlay').style.display = 'none';
}

function previewMeterPhoto(input) {
    const file = input.files[0];
    if (!file) return;
    const url = URL.createObjectURL(file);
    const preview = document.getElementById('meter-photo-preview');
    const placeholder = document.querySelector('.meter-photo-placeholder');
    preview.src = url;
    preview.style.display = 'block';
    placeholder.style.display = 'none';
}