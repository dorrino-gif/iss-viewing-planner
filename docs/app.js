'use strict';
const $ = id => document.getElementById(id);
const colors = {best:'#b9e78c', partial:'#e8b873', poor:'#8f9d9b'};
let data, selected, map, zoneLayer, trackLayer, issMarker, baseMarker, orbitMode = false;
const format = (value, options) => new Intl.DateTimeFormat('en-US', {timeZone:'America/New_York', ...options}).format(new Date(value));
const day = value => format(value, {weekday:'short',month:'short',day:'numeric'});
const clock = value => format(value, {hour:'numeric',minute:'2-digit'});
const direction = degrees => ['N','NE','E','SE','S','SW','W','NW'][Math.round(degrees / 45) % 8];
const duration = seconds => `${Math.floor(seconds/60)}m ${seconds%60}s`;
const confidence = p => ({near_term:'Near-term estimate',tentative:'Tentative · 8–14 days',low:'Low confidence · 15–30 days'}[p.confidence]);
function text(id, value) { $(id).textContent = value; }
function notify(message) { $('notice').hidden = !message; text('notice',message); }
function splitTrack(points) {
  const segments = []; let current = [];
  for (const point of points) {
    if (current.length && Math.abs(current[current.length-1][1] - point[2]) > 180) { segments.push(current); current=[]; }
    current.push([point[1],point[2]]);
  }
  if (current.length) segments.push(current);
  return segments;
}
function clearLayers() {
  for (const layer of [zoneLayer,trackLayer,issMarker]) if (layer && map) map.removeLayer(layer);
  zoneLayer=trackLayer=issMarker=undefined;
}
function drawRegional() {
  if (!map || !selected) return;
  clearLayers();
  zoneLayer=L.geoJSON(selected.zones,{style:f=>({color:'#263b31',weight:.6,fillColor:colors[f.properties.quality],fillOpacity:.48}),onEachFeature:(f,layer)=>{
    const p=f.properties;
    const weather=p.weather ? `${Math.round(p.weather.cloud_cover)}% clouds` : 'Weather unavailable — geometry only';
    layer.bindPopup(`<strong>${p.quality[0].toUpperCase()+p.quality.slice(1)} viewing</strong><br>Visible elevation: ${p.max_elevation}°<br>${weather}<br>Sampled cell-center estimate`);
  }}).addTo(map);
  trackLayer=L.polyline(splitTrack(selected.track),{color:'#edc481',weight:2,opacity:.9,dashArray:'5 6'}).addTo(map);
  const closest=selected.track.reduce((a,b)=>Math.abs(new Date(a[0])-new Date(selected.peak))<Math.abs(new Date(b[0])-new Date(selected.peak))?a:b);
  issMarker=L.circleMarker([closest[1],closest[2]],{radius:6,color:'#14211a',weight:2,fillColor:'#d2ed91',fillOpacity:1}).bindTooltip('ISS at peak viewing time').addTo(map);
  map.fitBounds(zoneLayer.getBounds(),{padding:[15,15]});
}
function drawOrbit() {
  if (!map) return;
  clearLayers();
  const at=new Date(data.start).getTime()+Number($('orbit-time').value)*3600000;
  const points=data.orbit.filter(p=>Math.abs(new Date(p[0]).getTime()-at)<=45*60000);
  text('orbit-label', `${day(at)} · ${clock(at)}`);
  trackLayer=L.polyline(splitTrack(points),{color:'#e0be75',weight:2.5}).addTo(map);
  if(points.length){const nearest=points.reduce((a,b)=>Math.abs(new Date(a[0])-at)<Math.abs(new Date(b[0])-at)?a:b);issMarker=L.circleMarker([nearest[1],nearest[2]],{radius:7,color:'#14211a',fillColor:'#d2ed91',fillOpacity:1}).bindTooltip('Estimated ISS position').addTo(map);}
}
function setMode(orbit) {
  orbitMode=orbit; $('orbit-controls').hidden=!orbit;
  for(const [id,active] of [['regional-mode',!orbit],['orbit-mode',orbit]]){$(id).classList.toggle('active',active);$(id).setAttribute('aria-pressed',String(active));}
  if(orbit){map?.setView([20,-45],2);drawOrbit();}else drawRegional();
}
function selectPass(p, updateHash=true) {
  selected=p;
  text('detail-date',day(p.start));text('detail-time',`${clock(p.start)} – ${clock(p.end)}`);
  text('detail-quality',`${p.quality} viewing${p.weather?'':' · geometry'}`);$('detail-quality').className=`badge ${p.quality}`;
  text('detail-elevation',`${p.max_elevation}°`);text('detail-duration',duration(p.duration_seconds));
  text('detail-direction',`${direction(p.start_azimuth)} → ${direction(p.end_azimuth)}`);
  text('detail-cloud',p.weather?`${Math.round(p.weather.cloud_cover)}%`:'Unavailable');
  text('detail-confidence',confidence(p));
  text('detail-basis',p.weather?'Rating combines orbital geometry and forecast cloud cover. Clear skies are not guaranteed.':'Geometry-only rating. No cloud forecast is available for this pass.');
  $('download-event').disabled=false;
  if(updateHash) history.replaceState(null,'',`#pass=${p.id}`);
  document.querySelectorAll('.pass-card').forEach(el=>{const active=el.dataset.id===p.id;el.classList.toggle('selected',active);el.setAttribute('aria-pressed',String(active));});
  if(orbitMode)setMode(false);else drawRegional();
}
function renderList() {
  const filter=$('quality-filter').value;
  const passes=data.passes.filter(p=>new Date(p.end)>new Date()).filter(p=>filter==='all'||filter==='best'&&p.quality==='best'||filter==='weather'&&p.weather||filter==='geometry'&&!p.weather);
  text('filter-count',`${passes.length} window${passes.length===1?'':'s'}`);$('pass-list').replaceChildren();
  if(!passes.length){const empty=document.createElement('p');empty.className='empty';empty.textContent='No upcoming windows match this filter. Try another filter or refresh the forecast in Prefect.';$('pass-list').append(empty);return;}
  for(const p of passes){const card=document.createElement('button');card.className=`pass-card${selected?.id===p.id?' selected':''}`;card.dataset.id=p.id;card.setAttribute('aria-pressed',String(selected?.id===p.id));
    const badge=document.createElement('span');badge.className=`badge ${p.quality}`;badge.textContent=`${p.quality}${p.weather?'':' · geometry'}`;
    const arrow=document.createElement('span');arrow.className='arrow';arrow.textContent='↗';arrow.setAttribute('aria-hidden','true');
    const date=document.createElement('div');date.className='date';date.textContent=day(p.start);
    const time=document.createElement('div');time.className='time';time.textContent=`${clock(p.start)} – ${clock(p.end)}`;
    const facts=document.createElement('div');facts.className='facts';
    for(const value of [`↗ ${p.max_elevation}°`,duration(p.duration_seconds),p.weather?`${Math.round(p.weather.cloud_cover)}% clouds`:'No weather']){const span=document.createElement('span');span.textContent=value;facts.append(span);}
    const conf=document.createElement('p');conf.className='confidence';conf.textContent=confidence(p);
    card.append(badge,arrow,date,time,facts,conf);card.addEventListener('click',()=>selectPass(p));$('pass-list').append(card);
  }
}
function downloadSelected(){if(!selected)return;const blob=new Blob([ISSCalendar.calendar(data,[selected])],{type:'text/calendar;charset=utf-8'});const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download=`iss-raleigh-${selected.start.slice(0,10)}-${selected.id}.ics`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
async function init(){
  try{
    const response=await fetch('data/predictions.json',{cache:'no-store'});if(!response.ok)throw new Error('Forecast has not been published yet.');data=await response.json();
    const upcoming=data.passes.filter(p=>new Date(p.end)>new Date());
    text('location',data.location.name);text('coordinates',`${data.location.latitude.toFixed(4)}° N · ${Math.abs(data.location.longitude).toFixed(4)}° W`);
    text('next-pass',upcoming.length?`${day(upcoming[0].start)} · ${clock(upcoming[0].start)}`:'No windows in this forecast');text('pass-count',`${upcoming.length} upcoming`);
    text('updated',`${day(data.generated_at)} · ${clock(data.generated_at)}`);text('epoch',`Orbital epoch: ${day(data.orbital_epoch)}.`);
    const warnings=data.warnings.filter(w=>w.startsWith('Cloud forecasts'));
    if(Date.now()-new Date(data.generated_at).getTime()>36*3600000)warnings.unshift('This forecast is over 36 hours old. Refresh it in Prefect before relying on pass times or weather.');
    notify(warnings.join(' '));
    if(typeof L!=='undefined'){map=L.map('map',{scrollWheelZoom:false}).setView([data.location.latitude,data.location.longitude],7);L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',{attribution:'&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',maxZoom:15}).addTo(map);baseMarker=L.marker([data.location.latitude,data.location.longitude]).bindTooltip(data.location.name).addTo(map);}
    else{$('map').textContent='Map library could not load. Viewing windows and calendar downloads remain available.';}
    const requested=new URLSearchParams(location.hash.slice(1)).get('pass');
    const initial=data.passes.find(p=>p.id===requested)||upcoming[0];
    if(initial)selectPass(initial,false);else{text('detail-date','No upcoming visible passes');text('detail-time','Refresh the forecast to check again.');}
    renderList();$('quality-filter').addEventListener('change',renderList);$('download-event').addEventListener('click',downloadSelected);
    $('regional-mode').addEventListener('click',()=>setMode(false));$('orbit-mode').addEventListener('click',()=>setMode(true));$('orbit-time').addEventListener('input',drawOrbit);
  }catch(error){notify(`Forecast unavailable. ${error.message}`);text('next-pass','Forecast unavailable');text('detail-date','Awaiting published data');$('pass-list').textContent='No forecast is available. Run the refresh workflow in Prefect Cloud to publish one.';}
}
init();
