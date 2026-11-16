(function (root) {
  'use strict';
  const escape = value => String(value).replace(/\\/g, '\\\\').replace(/\r\n|\r|\n/g, '\\n').replace(/;/g, '\\;').replace(/,/g, '\\,');
  function fold(value) {
    const lines = []; let current = '';
    for (const char of value) {
      if (new TextEncoder().encode(current + char).length > 75) { lines.push(current); current = ' '; }
      current += char;
    }
    lines.push(current); return lines.join('\r\n');
  }
  function calendar(data, passes) {
    const stamp = value => new Date(value).toISOString().replace(/[-:]/g, '').replace(/\.\d{3}Z$/, 'Z');
    const lines = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//ISS Viewing Planner//EN', 'CALSCALE:GREGORIAN', 'METHOD:PUBLISH'];
    for (const p of passes) {
      const cloud = p.weather ? `${Math.round(p.weather.cloud_cover)}%` : 'unavailable; geometry only';
      lines.push('BEGIN:VEVENT', `UID:${p.id}@iss-viewing-planner`, `DTSTAMP:${stamp(data.generated_at)}`,
        `DTSTART:${stamp(p.start)}`, `DTEND:${stamp(p.end)}`, `SUMMARY:${escape('ISS viewing — ' + data.location.name)}`,
        `LOCATION:${escape(data.location.name)}`, `DESCRIPTION:${escape(`Peak elevation ${p.max_elevation} degrees. Clouds: ${cloud}. Look from azimuth ${p.start_azimuth} to ${p.end_azimuth} degrees. Times are estimates. Recheck before viewing. This imported event will not update automatically.`)}`,
        `URL:https://dorrino-gif.github.io/iss-viewing-planner/#pass=${p.id}`, 'BEGIN:VALARM', 'ACTION:DISPLAY',
        'DESCRIPTION:ISS viewing begins soon', `TRIGGER:-PT${data.reminder_minutes}M`, 'END:VALARM', 'END:VEVENT');
    }
    lines.push('END:VCALENDAR'); return lines.map(fold).join('\r\n') + '\r\n';
  }
  if (typeof module !== 'undefined') module.exports = {calendar, fold, escape};
  else root.ISSCalendar = {calendar};
})(typeof window !== 'undefined' ? window : globalThis);
