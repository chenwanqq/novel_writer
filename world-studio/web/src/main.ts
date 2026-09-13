import './style.css';
import { escapeXML as esc, scaledPoint, viewPoint } from './geometry.mjs';

type Data = { [key: string]: any };
type Item = { id: string; kind: string; name: string; text: string; status: string; data: Data; [key: string]: any };
type State = Record<string, Item>;
type Draft = { id: string; world: string; branch: string; base: string; head: string; version: number; state: State; committed: string | null };
type World = { id: string; name: string; branch: string; head: string };
type View = { x: number; y: number; w: number; h: number };
const $ = <T extends Element = HTMLElement>(selector: string) => document.querySelector<T>(selector)!;
const app = $('#app');
let worlds: World[] = [], world = '', branch = 'main', draft: Draft | null = null;
let state: State = {}, mapId = '', selected = '', tool = 'select', historical = false;
let view: View = {x: 0, y: 0, w: 1600, h: 1000};
let undo: State[] = [], redo: State[] = [], pending: number[][] = [], routeStart = '';
let serial = 0, savedSerial = 0, saveQueue: Promise<void> = Promise.resolve(), timer: ReturnType<typeof setTimeout>;
const images = new Map<string, string>();
const layers: Record<string, boolean> = { place: true, route: true, region: true, background: true };
const hash = new URLSearchParams(location.hash.slice(1));
if (hash.has('token')) { sessionStorage.setItem('world-token', hash.get('token')!); history.replaceState(null, '', location.pathname); }
const token = sessionStorage.getItem('world-token') || '';

async function api<T = any>(method: string, params: Data = {}): Promise<T> {
  const response = await fetch(`/api/${method}`, { method: 'POST',
    headers: {'Content-Type': 'application/json', Authorization: `Bearer ${token}`}, body: JSON.stringify(params) });
  const body = await response.json();
  if (!response.ok) throw new Error(`${body.message || body.code}${body.details ? '\n' + JSON.stringify(body.details, null, 2) : ''}`);
  return body.result;
}
function status(message: string, error = false) {
  $('#status').textContent = message; $('#status').classList.toggle('error', error);
}
function report(error: unknown) { status(error instanceof Error ? error.message : String(error), true); }
function ask(title: string, defaultValue: string | null = ''): Promise<string | null> {
  return new Promise(resolve => {
    const dialog = document.createElement('dialog'); dialog.className = 'form-dialog';
    dialog.innerHTML = `<form method="dialog"><h2>${esc(title)}</h2>${defaultValue !== null ? `<input aria-label="${esc(title)}" value="${esc(defaultValue)}" autocomplete="off">` : ''}<div class="dialog-actions"><button value="cancel">取消</button><button value="ok" class="primary">确认</button></div></form>`;
    document.body.append(dialog);
    dialog.addEventListener('close', () => { const value = dialog.returnValue === 'ok' ? (dialog.querySelector('input')?.value ?? 'yes') : null; dialog.remove(); resolve(value); }, {once: true});
    dialog.showModal(); dialog.querySelector('input')?.select();
  });
}
function uid(prefix: string) { return `${prefix}_${crypto.randomUUID().replaceAll('-', '').slice(0, 12)}`; }
function record(kind: string, name: string, data: Data): Item {
  return {id: uid(kind), kind, name, text: '', nature: 'fictional', status: 'accepted',
    tags: [], sources: [], refs: [], depends_on: [], supersedes: [], valid_from: null, valid_to: null, data};
}
function currentMap() { return state[mapId]; }
function localKey() { return `world-draft:${world}:${branch}`; }
function editable() { if (!draft || historical) { status('当前为历史只读视图，请返回最新版本后编辑。', true); return false; } return true; }
function checkpoint() { undo.push(structuredClone(state)); if (undo.length > 80) undo.shift(); redo = []; }
function changed() {
  serial++; render();
  if (draft) localStorage.setItem(localKey(), JSON.stringify({draft: {...draft, state}, serial}));
  status('有未提交修改 · 正在保存草稿'); clearTimeout(timer);
  timer = setTimeout(() => { void save().catch(report); }, 600);
}
async function save() {
  clearTimeout(timer);
  saveQueue = saveQueue.catch(() => {}).then(async () => {
    if (!draft || historical || savedSerial === serial) return;
    const captured = draft, snapshot = structuredClone(state), seq = serial;
    for (const item of Object.values(snapshot)) if (item.kind === 'route') {
      const low = item.data.min_days, high = item.data.max_days;
      if ((low == null) !== (high == null) || (low != null && (low < 0 || high < low))) {
        throw new Error(`“${item.name}”的耗时尚未填完整：请同时填写最短、最长天数，或将两项都留空。`);
      }
    }
    const result = await api<Draft>('save_draft', {ident: captured.id, version: captured.version, state: snapshot});
    if (draft?.id === captured.id) {
      draft = {...result, state}; savedSerial = seq;
      localStorage.setItem(localKey(), JSON.stringify({draft, serial}));
      status(savedSerial === serial ? '草稿已保存 · 尚未提交到世界' : '仍有新修改待保存');
    }
  });
  return saveQueue;
}

app.innerHTML = `<header><h1>World Studio</h1><span class="divider"></span><label class="world-label">当前世界 <select id="world" aria-label="当前世界"></select></label><label>版本 <select id="revision" aria-label="世界版本"></select></label><div class="spacer"></div><button id="save">保存草稿</button><button id="commit" class="primary">提交版本 ↗</button></header>
<main><aside class="left"><h2>世界地图</h2><div class="section-heading">地图列表 <button id="world-new" title="创建世界">新世界</button></div><nav id="maps"></nav><div class="stack"><button id="map-new">＋ 创建空白地图</button><button id="import-new">↑ 导入背景图</button></div><h3>图层</h3><div id="layers"></div><h3>地点搜索</h3><input id="search" placeholder="名称或说明…" aria-label="地点搜索"><div id="search-results"></div><div class="left-bottom"><button id="export-svg">导出 SVG</button><button id="export-png">导出 PNG</button></div></aside>
<section class="workspace"><div class="toolbar"><button data-tool="select" class="active">↖ 选择</button><button data-tool="place">♧ 地点</button><button data-tool="route">⌁ 路线</button><button data-tool="region">▱ 区域</button><i></i><button id="undo">↶ 撤销</button><button id="redo">↷ 重做</button><button id="finish" hidden>完成区域</button></div><div class="canvas-wrap"><svg id="canvas" role="img" aria-label="世界地图编辑画布" preserveAspectRatio="none"></svg><div id="empty"><h2>从一个地点开始</h2><p>创建空白地图，或导入已有世界的底图。<br>地点、路线和故事将共享同一套设定。</p></div><div class="zoom"><button id="zoom-out" aria-label="缩小">−</button><span id="zoom-label">100%</span><button id="zoom-in" aria-label="放大">＋</button><button id="fit">适合画布</button></div></div><div id="hint">拖动空白处平移，滚轮缩放；地点与顶点可拖动。</div></section>
<aside class="right"><div class="section-heading"><h2 id="inspector-title">地图信息</h2><button id="delete" title="删除选中对象">删除</button></div><div id="inspector"></div><section class="route-panel"><h3>路线查询</h3><label>起点<select id="from"></select></label><label>终点<select id="to"></select></label><label>已满足条件<input id="conditions" placeholder="逗号分隔，例如：关口开放"></label><label>可用天数<input id="days" type="number" min="0" placeholder="可选"></label><button id="route-query">检查行程</button><output id="route-result">查询使用当前查看的正式世界版本。</output></section><button id="rebase">比较并重新应用草稿</button><pre id="review" hidden></pre></aside></main>
<footer><span id="status" role="status">正在连接本地资料库…</span><span id="coordinates">地图单位 · 未设置比例尺</span></footer><input id="file" type="file" accept="image/png,image/jpeg,image/webp" hidden>`;

$('#layers').innerHTML = Object.entries({background: '底图', place: '地点', route: '路线', region: '区域'}).map(([key, title]) => `<label class="toggle">${title}<input type="checkbox" data-layer="${key}" checked></label>`).join('');
function field(label: string, key: string, value: any, type = 'text') {
  return `<label>${label}<input data-field="${key}" type="${type}" value="${esc(value ?? '')}" ${historical ? 'disabled' : ''}></label>`;
}
function selectField(label: string, key: string, value: string, options: [string, string][]) {
  return `<label>${label}<select data-field="${key}" ${historical ? 'disabled' : ''}>${options.map(([id, name]) => `<option value="${esc(id)}" ${id === value ? 'selected' : ''}>${esc(name)}</option>`).join('')}</select></label>`;
}
function mapItems(kind: string) { return Object.values(state).filter(r => r.kind === kind && r.data.map === mapId); }
function renderInspector() {
  const item = state[selected] || currentMap();
  $('#inspector-title').textContent = item ? ({place: '地点信息', route: '路线信息', region: '区域信息', map: '地图信息'}[item.kind] || '对象信息') : '地图信息';
  if (!item) { $('#inspector').innerHTML = '<p class="muted">选择地图或对象以查看属性。</p>'; return; }
  let html = field('名称', 'name', item.name);
  if (item.kind === 'place') {
    html += selectField('关联实体', 'entity', item.data.entity, Object.values(state).filter(r => r.kind === 'entity').map(r => [r.id, r.name]));
    html += `<div class="pair">${field('X 坐标', 'x', item.data.x, 'number')}${field('Y 坐标', 'y', item.data.y, 'number')}</div>`;
    html += selectField('下级地图', 'child_map', item.data.child_map || '', [['', '无'], ...Object.values(state).filter(r => r.kind === 'map' && r.id !== mapId).map(r => [r.id, r.name] as [string, string])]);
  }
  if (item.kind === 'map') {
    html += `<div class="pair">${field('画布宽度', 'width', item.data.width, 'number')}${field('画布高度', 'height', item.data.height, 'number')}</div>`;
    html += field('每公里画布单位（可选）', 'units_per_km', item.data.units_per_km, 'number');
    html += `<button id="replace-bg" ${historical ? 'disabled' : ''}>替换底图</button><button id="remove-bg" ${historical || !item.data.asset ? 'disabled' : ''}>移除底图</button>`;
  }
  if (item.kind === 'route') {
    html += field('通行方式', 'mode', item.data.mode);
    html += `<div class="pair">${field('最短天数', 'min_days', item.data.min_days, 'number')}${field('最长天数', 'max_days', item.data.max_days, 'number')}</div>`;
    html += selectField('通行状态', 'availability', item.data.availability, [['open', '开放'], ['closed', '封闭'], ['unknown', '未知']]);
    html += selectField('方向', 'bidirectional', String(item.data.bidirectional), [['true', '双向'], ['false', '单向']]);
    html += field('条件（逗号分隔）', 'conditions', (item.data.conditions || []).join('，'));
  }
  if (item.kind === 'region') html += field('区域颜色', 'color', item.data.color, 'color');
  html += `<label>说明<textarea data-field="text" ${historical ? 'disabled' : ''}>${esc(item.text)}</textarea></label><p class="object-id">${esc(item.id)}</p>`;
  $('#inspector').innerHTML = html;
  $('#inspector').querySelectorAll<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>('[data-field]').forEach(input => input.onchange = () => {
    if (!editable()) return;
    const key = input.dataset.field!;
    checkpoint();
    if (key === 'name' || key === 'text') item[key] = input.value;
    else if (key === 'conditions') item.data[key] = input.value.split(/[,，]/).map(s => s.trim()).filter(Boolean);
    else if (key === 'bidirectional') item.data[key] = input.value === 'true';
    else if (input instanceof HTMLInputElement && input.type === 'number') item.data[key] = input.value === '' ? null : Number(input.value);
    else item.data[key] = input.value || null;
    changed();
  });
  document.querySelector('#replace-bg')?.addEventListener('click', () => chooseFile(false));
  document.querySelector('#remove-bg')?.addEventListener('click', () => { if (editable()) { checkpoint(); item.data.asset = null; changed(); } });
}

function render() {
  const maps = Object.values(state).filter(r => r.kind === 'map');
  $('#maps').innerHTML = maps.map(m => `<button class="map-item ${m.id === mapId ? 'active' : ''}" data-map="${m.id}">▧ <span>${esc(m.name)}</span></button>`).join('');
  $('#maps').querySelectorAll<HTMLButtonElement>('[data-map]').forEach(b => b.onclick = () => { mapId = b.dataset.map!; selected = ''; pending = []; routeStart = ''; fit(); render(); });
  $('#empty').toggleAttribute('hidden', !!currentMap());
  $('#commit').toggleAttribute('disabled', historical || !draft);
  $('#save').toggleAttribute('disabled', historical || !draft);
  $('#undo').toggleAttribute('disabled', historical || undo.length === 0);
  $('#redo').toggleAttribute('disabled', historical || redo.length === 0);
  const places = mapItems('place');
  for (const id of ['from', 'to']) {
    const el = $<HTMLSelectElement>(`#${id}`), old = el.value;
    el.innerHTML = places.map(p => `<option value="${p.id}">${esc(p.name)}</option>`).join('');
    if (places.some(p => p.id === old)) el.value = old;
  }
  renderInspector(); renderCanvas(); searchPlaces();
  if (currentMap()?.data.asset && !images.has(currentMap().data.asset)) {
    const asset = currentMap().data.asset;
    void api('background', {asset}).then(r => { images.set(asset, r.url); renderCanvas(); }).catch(report);
  }
}
function fit() { const m = currentMap(); if (m) view = {x: -m.data.width * .05, y: -m.data.height * .05, w: m.data.width * 1.1, h: m.data.height * 1.1}; }
function shapeContent(exporting = false) {
  const m = currentMap(); if (!m) return '';
  let content = '';
  if (layers.background && m.data.asset && images.has(m.data.asset)) content += `<image href="${images.get(m.data.asset)}" width="${m.data.width}" height="${m.data.height}"/>`;
  for (const r of mapItems('region')) if (layers.region) {
    const points = r.data.points as number[][];
    content += `<polygon data-id="${r.id}" points="${points.map(p => p.join(',')).join(' ')}" fill="${esc(r.data.color)}" fill-opacity=".6" stroke="#769c8c" stroke-width="2"/>`;
    const cx = points.reduce((s, p) => s + p[0], 0) / points.length, cy = points.reduce((s, p) => s + p[1], 0) / points.length;
    content += `<text x="${cx}" y="${cy}" text-anchor="middle" fill="#638b7c" font-size="24" font-style="italic" pointer-events="none">${esc(r.name)}</text>`;
  }
  for (const r of mapItems('route')) if (layers.route) {
    const a = state[r.data.from], b = state[r.data.to]; if (!a || !b) continue;
    const points = [[a.data.x, a.data.y], ...(r.data.points || []), [b.data.x, b.data.y]];
    content += `<polyline data-id="${r.id}" points="${points.map(p => p.join(',')).join(' ')}" fill="none" stroke="${r.data.availability === 'closed' ? '#b96457' : '#62969d'}" stroke-width="${r.id === selected && !exporting ? 5 : 3}" ${r.data.availability !== 'open' ? 'stroke-dasharray="8 5"' : ''} ${!r.data.bidirectional ? 'marker-end="url(#arrow)"' : ''}/>`;
  }
  for (const p of mapItems('place')) if (layers.place) {
    content += `<g data-id="${p.id}" class="place"><circle cx="${p.data.x}" cy="${p.data.y}" r="${p.id === selected && !exporting ? 13 : 10}" fill="#176b70" stroke="white" stroke-width="3"/><text x="${p.data.x + 20}" y="${p.data.y + 6}" fill="#193943" font-size="20">${esc(p.name)}</text></g>`;
  }
  if (!exporting) {
    const item = state[selected];
    if (item && ['region', 'route'].includes(item.kind)) (item.data.points || []).forEach((p: number[], index: number) => {
      content += `<circle data-vertex="${index}" cx="${p[0]}" cy="${p[1]}" r="7" fill="white" stroke="#176b60" stroke-width="2"/>`;
    });
    if (pending.length) content += `<polyline points="${pending.map(p => p.join(',')).join(' ')}" fill="none" stroke="#176b60" stroke-dasharray="6 4" stroke-width="3"/>`;
  }
  return content;
}
function defs() { return '<defs><pattern id="grid" width="50" height="50" patternUnits="userSpaceOnUse"><circle cx="1" cy="1" r="1" fill="#bacbd0"/></pattern><marker id="arrow" markerWidth="8" markerHeight="8" refX="8" refY="4" orient="auto"><path d="M0 0 L8 4 L0 8" fill="none" stroke="#62969d"/></marker></defs>'; }
function renderCanvas() {
  const svg = $<SVGSVGElement>('#canvas');
  svg.setAttribute('viewBox', `${view.x} ${view.y} ${view.w} ${view.h}`);
  svg.innerHTML = defs() + `<rect x="${view.x}" y="${view.y}" width="${view.w}" height="${view.h}" fill="url(#grid)"/>` + shapeContent();
  $('#zoom-label').textContent = `${Math.round((currentMap()?.data.width || 1600) / view.w * 100)}%`;
}
function searchPlaces() {
  const query = $<HTMLInputElement>('#search').value;
  $('#search-results').innerHTML = query ? mapItems('place').filter(r => `${r.name} ${r.text}`.includes(query)).map(r => `<button data-result="${r.id}">${esc(r.name)}</button>`).join('') : '';
  $('#search-results').querySelectorAll<HTMLButtonElement>('button').forEach(b => b.onclick = () => { selected = b.dataset.result!; const p = state[selected].data; view.x = p.x - view.w / 2; view.y = p.y - view.h / 2; render(); });
}

async function refreshVersions() {
  const revisions = await api<any[]>('revisions', {world});
  const head = await api<string>('head', {world, branch});
  $('#revision').innerHTML = `<option value="latest">最新 · ${esc(head.slice(-6))}</option>` + revisions.map(r => `<option value="${r.id}">${esc(r.id.slice(-6))} · ${esc(r.decision.slice(0, 18))}</option>`).join('');
}
async function loadWorld(id: string, selectedBranch = 'main') {
  if (draft && !historical) await save();
  world = id; branch = selectedBranch; historical = false; undo = []; redo = []; selected = ''; pending = []; serial = 0; savedSerial = 0;
  const stored = localStorage.getItem(localKey());
  if (stored) {
    const cached = JSON.parse(stored);
    try {
      const remote = await api<Draft>('draft', {ident: cached.draft.id});
      if (!remote.committed) {
        draft = remote;
        // A failed network save may leave a newer local state; preserve it if server version matches.
        if (cached.draft.version === remote.version) draft.state = cached.draft.state;
      } else draft = await api<Draft>('new_draft', {world, branch});
    } catch { draft = await api<Draft>('new_draft', {world, branch}); }
  } else draft = await api<Draft>('new_draft', {world, branch});
  state = draft!.state; mapId = Object.values(state).find(r => r.kind === 'map')?.id || '';
  serial = 1; await refreshVersions(); fit(); render();
  status(draft!.head === draft!.base ? '草稿已载入 · 修改不会自动提交正式世界' : '世界已有新版本；草稿保留，可比较并重新应用。', draft!.head !== draft!.base);
}
async function refreshWorlds() {
  worlds = await api<World[]>('worlds');
  $('#world').innerHTML = worlds.length ? worlds.map(w => `<option value="${w.id}:${w.branch}">${esc(w.name)} / ${esc(w.branch)}</option>`).join('') : '<option>尚无世界</option>';
}
async function createWorld() {
  const name = await ask('世界名称'); if (!name?.trim()) return;
  const id = uid('world'); await api('create_world', {world: id, name}); await refreshWorlds();
  $<HTMLSelectElement>('#world').value = `${id}:main`; await loadWorld(id);
}
async function newMap(background?: Data) {
  if (!world) { await createWorld(); if (!world) return; }
  if (!editable()) return;
  const name = await ask('地图名称', background ? '新地图' : '空白地图'); if (!name?.trim()) return;
  checkpoint(); const m = record('map', name, {...(background || {width: 1600, height: 1000}), units_per_km: null});
  state[m.id] = m; mapId = m.id; selected = ''; fit(); changed();
}
let fileIsNew = true;
function chooseFile(isNew: boolean) { if (historical) return; fileIsNew = isNew; $<HTMLInputElement>('#file').click(); }
$<HTMLInputElement>('#file').onchange = async event => {
  try {
    const file = (event.target as HTMLInputElement).files?.[0]; if (!file) return;
    const data = await new Promise<string>((resolve, reject) => { const reader = new FileReader(); reader.onload = () => resolve(String(reader.result)); reader.onerror = reject; reader.readAsDataURL(file); });
    const image = await api('upload', {content_base64: data.split(',')[1]}); images.set(image.asset, data);
    if (fileIsNew) await newMap(image);
    else if (editable() && currentMap()) {
      const mode = await ask('替换底图：输入“保留”保持原坐标与画布，输入“缩放”按新图片尺寸缩放全部对象。', '保留');
      if (!['保留', '缩放'].includes(mode || '')) return;
      checkpoint(); const m = currentMap(), old = [m.data.width, m.data.height], size = [image.width, image.height];
      if (mode === '缩放') {
        for (const r of Object.values(state).filter(r => r.data.map === mapId)) {
          if (r.kind === 'place') [r.data.x, r.data.y] = scaledPoint([r.data.x, r.data.y], old, size);
          if (r.data.points) r.data.points = r.data.points.map((p: number[]) => scaledPoint(p, old, size));
        }
        Object.assign(m.data, image);
      } else m.data.asset = image.asset;
      fit(); changed();
    }
  } catch (e) { report(e); } finally { $<HTMLInputElement>('#file').value = ''; }
};

const canvas = $<SVGSVGElement>('#canvas');
let gesture: {point: number[]; view: View; id?: string; vertex?: number; moved: boolean; before: State} | null = null;
function point(e: MouseEvent) { return viewPoint(e.clientX, e.clientY, canvas.getBoundingClientRect(), view); }
canvas.onpointerdown = async e => {
  if (!currentMap()) return;
  const target = (e.target as Element).closest('[data-id]');
  const vertex = (e.target as Element).getAttribute('data-vertex');
  const id = target?.getAttribute('data-id') || '';
  if (tool === 'select') {
    if (id) selected = id; else if (vertex === null) selected = '';
    gesture = {point: [e.clientX, e.clientY], view: {...view}, id: !historical ? (vertex !== null ? selected : id) : '',
      vertex: vertex !== null ? Number(vertex) : undefined, moved: false, before: structuredClone(state)};
    canvas.setPointerCapture(e.pointerId); renderInspector(); renderCanvas(); return;
  }
  if (!editable()) return;
  const p = point(e);
  if (tool === 'place') {
    const name = await ask('地点名称'); if (!name?.trim()) return;
    checkpoint(); const entity = record('entity', name, {}); state[entity.id] = entity;
    const place = record('place', name, {map: mapId, entity: entity.id, x: p[0], y: p[1], child_map: null});
    state[place.id] = place; selected = place.id; changed();
  } else if (tool === 'region') { pending.push(p); renderCanvas(); }
  else if (tool === 'route') {
    if (id && state[id]?.kind === 'place') {
      if (!routeStart) { routeStart = id; pending = [[state[id].data.x, state[id].data.y]]; status('点击空白处添加折点，再点击终点。'); }
      else if (id !== routeStart) {
        checkpoint(); const r = record('route', `${state[routeStart].name} — ${state[id].name}`, {map: mapId, from: routeStart, to: id,
          points: pending.slice(1), mode: '步行', bidirectional: true, min_days: null, max_days: null, availability: 'open', conditions: []});
        state[r.id] = r; selected = r.id; pending = []; routeStart = ''; changed();
      }
    } else if (routeStart) pending.push(p);
    renderCanvas();
  }
};
canvas.onpointermove = e => {
  const p = point(e); $('#coordinates').textContent = `X ${p[0].toFixed(1)} · Y ${p[1].toFixed(1)} | ${currentMap()?.data.units_per_km ? '已设置比例尺' : '地图单位 · 无比例尺'}`;
  if (!gesture) return;
  const dx = (e.clientX - gesture.point[0]) / canvas.getBoundingClientRect().width * gesture.view.w;
  const dy = (e.clientY - gesture.point[1]) / canvas.getBoundingClientRect().height * gesture.view.h;
  if (Math.abs(dx) + Math.abs(dy) < .5 && !gesture.moved) return;
  gesture.moved = true;
  const item = state[gesture.id || ''];
  if (item?.kind === 'place') { item.data.x = gesture.before[item.id].data.x + dx; item.data.y = gesture.before[item.id].data.y + dy; }
  else if (item && gesture.vertex !== undefined) {
    const old = gesture.before[item.id].data.points[gesture.vertex]; item.data.points[gesture.vertex] = [old[0] + dx, old[1] + dy];
  } else { view.x = gesture.view.x - dx; view.y = gesture.view.y - dy; }
  renderCanvas();
};
canvas.onpointerup = () => {
  if (gesture?.moved && gesture.id && (state[gesture.id]?.kind === 'place' || gesture.vertex !== undefined)) {
    undo.push(gesture.before); redo = []; changed();
  }
  gesture = null; renderInspector();
};
canvas.onpointercancel = () => { if (gesture) { state = gesture.before; view = gesture.view; } gesture = null; render(); };
function zoom(factor: number) { const w = view.w * factor, h = view.h * factor; view = {x: view.x + (view.w - w) / 2, y: view.y + (view.h - h) / 2, w, h}; renderCanvas(); }
canvas.addEventListener('wheel', e => { e.preventDefault(); zoom(e.deltaY > 0 ? 1.12 : .89); }, {passive: false});
document.querySelectorAll<HTMLButtonElement>('[data-tool]').forEach(b => b.onclick = () => {
  tool = b.dataset.tool!; pending = []; routeStart = '';
  document.querySelectorAll('[data-tool]').forEach(t => t.classList.toggle('active', t === b));
  $('#finish').hidden = tool !== 'region';
  $('#hint').textContent = ({select: '拖动空白处平移，滚轮缩放；地点与顶点可拖动。', place: '点击画布新增地点；可在属性中改绑已有实体。', route: '先点击起点，可点击空白添加折点，再点击终点。', region: '逐点绘制边界，完成后点击“完成区域”。'} as Data)[tool]; renderCanvas();
});
$('#finish').onclick = async () => { if (pending.length < 3 || !editable()) { status('区域至少需要三个顶点。', true); return; } const name = await ask('区域名称'); if (!name?.trim()) return; checkpoint(); const r = record('region', name, {map: mapId, points: pending, color: '#bdd8ca', entity: null}); state[r.id] = r; selected = r.id; pending = []; changed(); };
$('#delete').onclick = async () => {
  const id = selected || mapId; if (!state[id] || !editable()) return;
  const references = Object.values(state).filter(r => r.id !== id && ([...(r.refs || []), ...(r.depends_on || []), ...(r.supersedes || []), ...['map', 'entity', 'from', 'to', 'child_map'].map(k => r.data[k])].includes(id)));
  if (references.length) { status(`先解除引用：${references.map(r => r.name).join('、')}`, true); return; }
  if (!await ask(`删除“${state[id].name}”？修改仅进入草稿。`, null)) return;
  checkpoint(); delete state[id]; if (mapId === id) mapId = ''; selected = ''; changed();
};
$('#undo').onclick = () => { if (undo.length && editable()) { redo.push(structuredClone(state)); state = undo.pop()!; changed(); } };
$('#redo').onclick = () => { if (redo.length && editable()) { undo.push(structuredClone(state)); state = redo.pop()!; changed(); } };
$('#zoom-in').onclick = () => zoom(.8); $('#zoom-out').onclick = () => zoom(1.25); $('#fit').onclick = () => { fit(); renderCanvas(); };
$('#map-new').onclick = () => { void newMap().catch(report); }; $('#import-new').onclick = () => chooseFile(true);
$('#world-new').onclick = () => { void createWorld().catch(report); }; $('#save').onclick = () => { void save().catch(report); };
$<HTMLSelectElement>('#world').onchange = e => { const [id, b] = (e.target as HTMLSelectElement).value.split(':'); void loadWorld(id, b).catch(report); };
$<HTMLSelectElement>('#revision').onchange = async e => {
  try {
    const revision = (e.target as HTMLSelectElement).value;
    if (revision === 'latest') { await loadWorld(world, branch); return; }
    await save(); historical = true; state = await api('snapshot', {world, revision});
    if (!state[mapId]) mapId = Object.values(state).find(r => r.kind === 'map')?.id || '';
    selected = ''; fit(); render(); status('历史版本 · 只读，不改变世界分支');
  } catch (e) { report(e); }
};
$('#search').addEventListener('input', searchPlaces);
$('#layers').querySelectorAll<HTMLInputElement>('input').forEach(i => i.onchange = () => { layers[i.dataset.layer!] = i.checked; renderCanvas(); });
$('#commit').onclick = async () => {
  try {
    if (!editable()) return; await save();
    const p = await api('propose_map', {ident: draft!.id, version: draft!.version});
    const preview = await api('preview', {proposal: p.change_set});
    $('#review').hidden = false; $('#review').textContent = JSON.stringify(preview, null, 2);
    if (preview.issues.length) { status('请先修复变更检查问题。', true); return; }
    if (!await ask(`本次变更新增、修改或删除 ${preview.changes.length} 个对象。确认采用并提交到世界？`, null)) return;
    const result = await api('commit_map', {ident: draft!.id, version: draft!.version, decision: '作者在地图编辑器预览差异后点击提交版本'});
    localStorage.removeItem(localKey()); draft = null; await loadWorld(world, branch); status(`已提交世界版本 ${result.revision}`);
  } catch (e) { report(e); }
};
$('#rebase').onclick = async () => {
  try {
    if (!editable()) return; await save();
    const head = await api('head', {world, branch}), diff = await api('diff', {world, before: draft!.base, after: head});
    $('#review').hidden = false; $('#review').textContent = JSON.stringify(diff, null, 2);
    if (!await ask(`世界有 ${diff.length} 个对象变化。重新应用不冲突的地图编辑？同对象冲突时保留草稿。`, null)) return;
    draft = await api('rebase_map', {ident: draft!.id, version: draft!.version}); state = draft!.state; undo = []; redo = []; serial++; savedSerial = serial;
    localStorage.setItem(localKey(), JSON.stringify({draft, serial})); await refreshVersions(); render(); status('已重新应用草稿，请检查并提交。');
  } catch (e) { $('#review').hidden = false; $('#review').textContent = String(e); report(e); }
};
$('#route-query').onclick = async () => {
  try {
    const revision = historical ? $<HTMLSelectElement>('#revision').value : draft!.base;
    const days = $<HTMLInputElement>('#days').value;
    const result = await api('route', {world, revision, start: $<HTMLSelectElement>('#from').value, end: $<HTMLSelectElement>('#to').value,
      conditions: $<HTMLInputElement>('#conditions').value.split(/[,，]/).map(s => s.trim()).filter(Boolean), available_days: days === '' ? null : Number(days)});
    $('#route-result').textContent = result.status === 'reachable' ? `${result.min_days}–${result.max_days} 天${result.timing ? ' · ' + ({impossible: '时间不足', possible: '时间可行', uncertain: '取决于实际耗时'} as Data)[result.timing] : ''}` : result.status === 'unreachable' ? '不可达：当前正式版本没有可用路径。' : '信息不足：需要确认通行条件或耗时。';
  } catch (e) { $('#route-result').textContent = '请先提交地图，再查询正式版本中的地点。'; report(e); }
};
async function exportMap(format: 'svg' | 'png') {
  const m = currentMap(); if (!m) return;
  if (m.data.asset && !images.has(m.data.asset)) images.set(m.data.asset, (await api('background', {asset: m.data.asset})).url);
  const points = Object.values(state).filter(r => r.data.map === mapId).flatMap(r => r.kind === 'place' ? [[r.data.x, r.data.y]] : (r.data.points || []));
  const x = Math.min(0, ...points.map(p => p[0])) - 40, y = Math.min(0, ...points.map(p => p[1])) - 40;
  const w = Math.max(m.data.width, ...points.map(p => p[0])) - x + 120, h = Math.max(m.data.height, ...points.map(p => p[1])) - y + 80;
  const rev = historical ? $<HTMLSelectElement>('#revision').value : `${draft!.base} / 草稿`;
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}" viewBox="${x} ${y} ${w} ${h}" font-family="sans-serif">${defs()}<rect x="${x}" y="${y}" width="${w}" height="${h}" fill="#edf2f5"/>${shapeContent(true)}<text x="${x + 20}" y="${y + h - 20}" font-size="16" fill="#193943">${esc(m.name)} · ${esc(rev)}</text></svg>`;
  let blob = new Blob([svg], {type: 'image/svg+xml'});
  if (format === 'png') {
    const url = URL.createObjectURL(blob);
    try {
      const img = new Image(); img.src = url; await img.decode();
      const c = document.createElement('canvas'), scale = Math.min(1, 4096 / Math.max(w, h));
      c.width = Math.ceil(w * scale); c.height = Math.ceil(h * scale); c.getContext('2d')!.drawImage(img, 0, 0, c.width, c.height);
      blob = await new Promise<Blob>((resolve, reject) => c.toBlob(b => b ? resolve(b) : reject(new Error('PNG export failed'))));
    } finally { URL.revokeObjectURL(url); }
  }
  const url = URL.createObjectURL(blob), a = document.createElement('a'); a.href = url; a.download = `${m.name}.${format}`; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000); status(`已导出 ${format.toUpperCase()}`);
}
$('#export-svg').onclick = () => { void exportMap('svg').catch(report); }; $('#export-png').onclick = () => { void exportMap('png').catch(report); };
window.addEventListener('beforeunload', e => { if (savedSerial !== serial && draft && !historical) { e.preventDefault(); e.returnValue = ''; } });
void (async () => { try { await refreshWorlds(); if (worlds.length) await loadWorld(worlds[0].id, worlds[0].branch); else { render(); status('资料库已连接 · 点击“新世界”开始。'); } } catch (e) { render(); report(e); } })();
