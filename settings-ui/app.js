'use strict';
// This exact resource is packaged by both native hosts. No server or CDN is used.
const $ = (selector, root = document) => root.querySelector(selector);
const el = (tag, attrs = {}, children = []) => {
    const node = document.createElement(tag);
    Object.entries(attrs).forEach(([key, value]) => {
        if (key === 'text') node.textContent = value;
        else if (key === 'class') node.className = value;
        else if (key.startsWith('on')) node.addEventListener(key.slice(2), value);
        else if (value !== undefined && value !== null) node.setAttribute(key, value);
    });
    children.forEach(child => node.appendChild(child));
    return node;
};
const pending = new Map();
let serial = 0;
window.CrossGesturesNative = {
    receive(message) {
        const waiter = pending.get(message.id);
        if (!waiter) return;
        pending.delete(message.id);
        if (message.error) waiter.reject(new Error(message.error));
        else waiter.resolve(message.result);
    },
};
if (window.chrome && window.chrome.webview)
    window.chrome.webview.addEventListener('message', event => window.CrossGesturesNative.receive(event.data));
function rpc(method, params = {}) {
    return new Promise((resolve, reject) => {
        const message = {id: ++serial, method, params};
        pending.set(message.id, {resolve, reject});
        if (window.chrome && window.chrome.webview) window.chrome.webview.postMessage(message);
        else if (window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.crossgestures)
            window.webkit.messageHandlers.crossgestures.postMessage(JSON.stringify(message));
        else {
            pending.delete(message.id);
            reject(new Error('无法连接设置程序，请从 CrossGestures 打开设置。'));
        }
    });
}

let state, page = 'general', profileId = 'global', query = '', busy = false, dialogSubmit, lastFocus;
const titles = {general: '常规', gestures: '手势', profiles: '应用配置', backup: '导入与恢复'};
const dirs = ['up', 'up-right', 'right', 'down-right', 'down', 'down-left', 'left', 'up-left'];
const arrows = ['↑', '↗', '→', '↘', '↓', '↙', '←', '↖'];
const buttons = {right: '右键', x1: 'X1', x2: 'X2', middle: '中键'};
const actionNames = {ShortcutAction: '快捷键', CopyAction: '复制', PasteAction: '粘贴', WindowAction: '窗口控制', CommandAction: 'Shell 命令', LaunchAction: '打开文件、应用或网址', PauseAction: '暂停手势', NoopAction: '空操作', CmdAction: 'Windows 命令', TextAction: '输入文本', ScriptAction: 'Lua 脚本', NativeAction: '原有动作'};
const operations = {'toggle-maximized': '最大化 / 恢复', minimize: '最小化', close: '关闭', 'toggle-fullscreen': '全屏 / 恢复', 'toggle-above': '置顶 / 取消置顶', 'dock-left': '靠左停靠', 'dock-right': '靠右停靠'};
const matcherNames = {wmClass: 'WM Class（窗口类）', desktopId: 'Desktop ID（桌面应用标识）', gtkApplicationId: 'GTK Application ID（应用标识）', sandboxedAppId: 'Snap / Flatpak ID（应用标识）', executable: '程序路径'};
const settingGroups = [
    ['运行与启动', [
        ['enabled', '启用鼠标手势', 'switch'], ['paused', '暂停手势', 'switch'],
        ['autostart-enabled', '登录后自动启动', 'switch'], ['minimize-to-tray', '最小化到托盘', 'switch', '关闭设置窗口后，手势仍在后台运行。'],
    ]],
    ['触发与识别', [
        ['trigger-buttons', '手势触发按钮', 'buttons'], ['middle-panel-enabled', '中键快捷面板', 'switch', '短按中键打开 4 × 4 快捷面板。'],
        ['direction-mode', '方向模式', 'mode'], ['start-threshold', '起始移动阈值', 'number', '', 2, 100, 1, 'px'],
        ['segment-threshold', '方向采样距离', 'number', '', 2, 200, 1, 'px'],
    ]],
    ['轨迹外观', [
        ['path-color', '轨迹颜色', 'color'], ['invalid-path-color', '无效轨迹颜色', 'color'],
        ['path-width', '轨迹宽度', 'number', '', 1, 24, .5, 'px'],
        ['fade-duration', '淡出时间', 'number', '', 0, 3000, 50, 'ms'],
        ['show-command-name', '显示手势名称', 'switch'], ['show-path', '显示手势轨迹', 'switch'],
    ]],
    ['Windows 设置', [
        ['disable-fullscreen', '全屏时停用手势', 'switch'], ['prefer-cursor-window', '作用于鼠标所在窗口', 'switch'],
        ['initial-timeout-enabled', '启用起始停留超时', 'switch'], ['initial-timeout', '起始停留超时', 'number', '', 50, 5000, 50, 'ms'],
        ['stay-timeout-enabled', '启用手势停留超时', 'switch'], ['stay-timeout', '手势停留超时', 'number', '', 50, 5000, 50, 'ms'],
    ]],
];
function toast(message) {
    $('#toast').textContent = message; $('#toast').hidden = false;
    clearTimeout(toast.timer); toast.timer = setTimeout(() => { $('#toast').hidden = true; }, 6500);
}
function setState(value) {
    state = value;
    if (!state.profiles.some(p => p.id === profileId)) profileId = 'global';
    const running = state.settings.enabled !== false && !state.settings.paused;
    $('#runtime-status').textContent = running ? '手势已启用' : '手势已暂停';
    $('#runtime-status').className = 'status' + (running ? ' running' : '');
    $('#version').textContent = state.platform + ' · ' + state.version;
}
async function mutate(method, params, redraw = true) {
    if (busy) throw new Error('请等待当前操作完成。');
    busy = true; $('#save-status').textContent = '正在保存…';
    try {
        const result = await rpc(method, Object.assign({revision: state.revision}, params));
        if (result && result.snapshot) setState(result.snapshot);
        else setState(await rpc('snapshot'));
        $('#save-status').textContent = '已保存';
        if (redraw) render();
        return result;
    } catch (error) {
        $('#save-status').textContent = '未保存';
        try { setState(await rpc('snapshot')); if (redraw) render(); } catch (_) { /* Keep the original error. */ }
        throw error;
    } finally { busy = false; }
}
function button(text, action, className = '') {
    return el('button', {type: 'button', text, class: className, onclick: async event => {
        const target = event.currentTarget; target.disabled = true;
        try { await action(); } catch (error) { toast(error.message); }
        finally { target.disabled = false; }
    }});
}
function toggle(label, value, change) {
    const input = el('input', {type: 'checkbox', 'aria-label': label}); input.checked = !!value;
    input.addEventListener('change', () => change(input.checked, input));
    return el('label', {class: 'switch'}, [input, el('span', {class: 'switch-track', 'aria-hidden': 'true'})]);
}
function select(items, value) {
    const node = el('select');
    items.forEach(([id, label]) => node.appendChild(el('option', {value: id, text: label})));
    node.value = value; return node;
}
function field(label, node) { return el('label', {class: 'field'}, [el('span', {text: label}), node]); }
function section(title, rows) { return el('section', {class: 'section'}, [el('h2', {class: 'section-title', text: title}), el('div', {class: 'card'}, rows)]); }
function settingRow(spec) {
    const [key, label, type, description, min, max, step, unit] = spec;
    const value = state.settings[key];
    const change = async (next, node) => {
        node.disabled = true;
        try { await mutate('setting', {key, value: next}, false); }
        catch (error) { toast(error.message); render(); }
        finally { node.disabled = false; }
    };
    let control;
    if (type === 'switch') control = toggle(label, value, change);
    else if (type === 'buttons') {
        control = el('div', {class: 'check-group'});
        ['right', 'x1', 'x2'].forEach(name => {
            const input = el('input', {type: 'checkbox', value: name}); input.checked = value.includes(name);
            input.addEventListener('change', () => change(Array.from(control.querySelectorAll('input:checked')).map(n => n.value), input));
            control.appendChild(el('label', {}, [input, el('span', {text: buttons[name]})]));
        });
    } else if (type === 'mode') {
        control = select([['4', '四方向'], ['8', '八方向']], String(value));
        control.addEventListener('change', () => change(Number(control.value), control));
    } else {
        control = el('input', {type, value, min, max, step, 'aria-label': label});
        control.addEventListener('change', () => {
            if (!control.checkValidity()) { control.reportValidity(); return; }
            change(type === 'number' ? Number(control.value) : control.value, control);
        });
    }
    const box = el('div', {class: 'control'}, [control]);
    if (unit) box.appendChild(el('span', {class: 'unit', text: unit}));
    return el('div', {class: 'setting-row'}, [el('div', {}, [el('div', {class: 'setting-label', text: label}), ...(description ? [el('div', {class: 'setting-description', text: description})] : [])]), box]);
}
function renderGeneral(root) {
    settingGroups.forEach(([name, specs]) => {
        const rows = specs.filter(spec => Object.prototype.hasOwnProperty.call(state.settings, spec[0])).map(settingRow);
        if (rows.length) root.appendChild(section(name, rows));
    });
    if (state.capabilities.legacy) root.appendChild(button(state.platform === 'Windows' ? '更多 Windows 设置…' : '兼容设置…', async () => { await rpc('legacy'); setState(await rpc('snapshot')); render(); }));
}
function accelerator(value) { return (value || '').replace(/<Control>/gi, 'Ctrl+').replace(/<Super>/gi, 'Win+').replace(/<([^>]+)>/g, '$1+').replace(/Return$/, 'Enter'); }
function actionLabel(action) {
    return actionNames[action.type] + (action.accelerator ? ' · ' + accelerator(action.accelerator) : action.operation ? ' · ' + operations[action.operation] : action.target ? ' · ' + action.target : action.summary ? ' · ' + action.summary : '');
}
function preview(directions) {
    const vectors = [[0,-1],[1,-1],[1,0],[1,1],[0,1],[-1,1],[-1,0],[-1,-1]];
    const points = [[0,0]];
    directions.forEach(d => { const v = vectors[dirs.indexOf(d)]; if (v) { const last = points[points.length-1]; points.push([last[0]+v[0],last[1]+v[1]]); } });
    const xs = points.map(p => p[0]), ys = points.map(p => p[1]);
    const minX = Math.min(...xs), minY = Math.min(...ys), w = Math.max(...xs)-minX, h = Math.max(...ys)-minY, scale = Math.min(32/(w||1),28/(h||1));
    const coords = points.map(p => [24+(p[0]-minX-w/2)*scale,20+(p[1]-minY-h/2)*scale]);
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg'); svg.setAttribute('viewBox','0 0 48 40'); svg.setAttribute('aria-hidden','true');
    const line = document.createElementNS(svg.namespaceURI, 'polyline'); line.setAttribute('points',coords.map(p => p.join(',')).join(' ')); line.setAttribute('class','preview-path'); svg.appendChild(line);
    const end = coords[coords.length-1], circle = document.createElementNS(svg.namespaceURI,'circle'); circle.setAttribute('cx',end[0]); circle.setAttribute('cy',end[1]); circle.setAttribute('r','3.5'); circle.setAttribute('fill','currentColor'); svg.appendChild(circle);
    return el('div',{class:'gesture-preview'},[svg]);
}
const currentProfile = () => state.profiles.find(p => p.id === profileId) || state.profiles[0];
function itemAction(label, text, callback) { const b = button(text, callback, 'icon-button'); b.title = label; b.setAttribute('aria-label',label); return b; }
function renderGestures(root) {
    const chooser = select(state.profiles.map(p => [p.id,p.name]),profileId); chooser.setAttribute('aria-label','应用配置');
    chooser.addEventListener('change',()=>{profileId=chooser.value;render();});
    const search = el('input',{type:'search',placeholder:'搜索手势',value:query,'aria-label':'搜索手势'});
    const list = el('div',{class:'list'});
    search.addEventListener('input',()=>{query=search.value;fillList();});
    root.appendChild(el('div',{class:'toolbar'},[chooser,search,button('＋ 添加手势',()=>editGesture(), 'primary')]));
    const profile=currentProfile();
    root.appendChild(el('div',{class:'profile-controls'},[el('label',{},[toggle('启用此配置',profile.enabled,async value=>{try {await mutate('profileToggle',{id:profile.id,enabled:value});}catch(e){toast(e.message);render();}}),el('span',{text:' 启用此配置'})]),el('span',{class:'secondary-text',text:profile.gestures.length+' 个手势'})]));
    root.appendChild(list);
    function fillList() {
        list.replaceChildren();
        const visible=profile.gestures.filter(g=>(g.name+' '+actionLabel(g.action)).toLowerCase().includes(query.toLowerCase()));
        visible.forEach((g)=>{
            const actions = el('div',{class:'item-actions'});
            if(state.capabilities.reorder) {
                const index=profile.gestures.indexOf(g);
                const up=itemAction('上移 '+g.name,'↑',()=>mutate('gestureMove',{profileId,id:g.id,delta:-1}));up.disabled=index===0;
                const down=itemAction('下移 '+g.name,'↓',()=>mutate('gestureMove',{profileId,id:g.id,delta:1}));down.disabled=index===profile.gestures.length-1;
                actions.append(up,down);
            }
            actions.append(button('编辑',()=>editGesture(g)),itemAction('删除 '+g.name,'×',()=>confirmDialog('删除手势','删除“'+g.name+'”？',()=>mutate('gestureDelete',{profileId,id:g.id}))));
            list.appendChild(el('article',{class:'gesture-item'},[preview(g.directions),el('div',{class:'item-main'},[el('div',{class:'item-title',text:g.name}),el('div',{class:'item-detail'},[el('span',{class:'badge',text:buttons[g.button]||g.button}),el('span',{text:g.directions.map(d=>arrows[dirs.indexOf(d)]).join(' ')})]),el('div',{class:'item-detail',text:actionLabel(g.action)})]),actions]));
        });
        if(!visible.length)list.appendChild(el('div',{class:'empty',text:query?'没有匹配的手势。':'还没有手势，点击“添加手势”创建。'}));
    }
    fillList();
}
function showDialog(title,body,submit,saveText='保存') {
    lastFocus=document.activeElement;$('#dialog-title').textContent=title;$('#dialog-body').replaceChildren(...body);$('#dialog-error').textContent='';$('#dialog-save').textContent=saveText;$('#dialog-save').disabled=false;dialogSubmit=submit;$('#modal').hidden=false;
    document.querySelector('main').setAttribute('inert','');$('.sidebar').setAttribute('inert','');
    const first=$('input,select,textarea,button', $('#dialog-body'));if(first)first.focus();else $('#dialog-save').focus();
}
function closeDialog(){if(busy)return;$('#modal').hidden=true;document.querySelector('main').removeAttribute('inert');$('.sidebar').removeAttribute('inert');if(lastFocus&&lastFocus.isConnected)lastFocus.focus();}
function confirmDialog(title,text,callback){showDialog(title,[el('p',{text})],async()=>{await callback();},'确认');}
function editGesture(gesture) {
    if(gesture&&gesture.editable===false){rpc('legacy').then(async()=>{setState(await rpc('snapshot'));render();}).catch(e=>toast(e.message));return;}
    const name=el('input',{value:gesture?gesture.name:'',required:'',maxlength:'120',placeholder:'手势名称'});
    const trigger=select(Object.entries(buttons).filter(([key])=>key!=='middle'),gesture?gesture.button:'right');
    let directionValues=gesture?gesture.directions.slice():[];
    const result=el('div',{class:'direction-result','aria-live':'polite'});
    const draw=el('canvas',{class:'draw-pad',width:'900',height:'260','aria-label':'用左键绘制手势，也可以使用下方方向按钮'});
    const context=draw.getContext('2d'); let points=[], drawing=false;
    function updateDirections(){result.textContent=directionValues.map(d=>arrows[dirs.indexOf(d)]).join(' ')||'请选择或绘制方向';}
    function point(event){const rect=draw.getBoundingClientRect();return[(event.clientX-rect.left)*900/rect.width,(event.clientY-rect.top)*260/rect.height];}
    draw.addEventListener('pointerdown',event=>{if(event.button!==0)return;drawing=true;points=[point(event)];context.clearRect(0,0,900,260);draw.setPointerCapture(event.pointerId);});
    draw.addEventListener('pointermove',event=>{if(!drawing)return;const p=point(event),last=points[points.length-1];context.strokeStyle=state.settings['path-color']||'#21834c';context.lineWidth=6;context.lineCap='round';context.beginPath();context.moveTo(...last);context.lineTo(...p);context.stroke();points.push(p);});
    draw.addEventListener('pointerup',async()=>{if(!drawing)return;drawing=false;try{const value=await rpc('recognize',{points});directionValues=value.directions;updateDirections();}catch(e){$('#dialog-error').textContent=e.message;}});
    draw.addEventListener('pointercancel',()=>{drawing=false;});
    const tools=el('div',{class:'direction-tools'});
    dirs.forEach((d,i)=>{if(state.settings['direction-mode']===4&&i%2)return;tools.appendChild(button(arrows[i],()=>{if(directionValues.length<32)directionValues.push(d);updateDirections();}));});
    tools.appendChild(button('清空',()=>{directionValues=[];updateDirections();context.clearRect(0,0,900,260);},'clear'));updateDirections();
    const type=select(state.capabilities.actions.map(key=>[key,actionNames[key]]),gesture?gesture.action.type:'ShortcutAction');
    const actionBox=el('div'); let actionInput;
    function actionFields(){
        actionBox.replaceChildren();const value=gesture&&gesture.action.type===type.value?gesture.action:{};
        if(type.value==='WindowAction')actionInput=select(state.capabilities.operations.map(op=>[op,operations[op]]),value.operation||'toggle-maximized');
        else if(['ShortcutAction','LaunchAction','CommandAction','CmdAction','TextAction','ScriptAction'].includes(type.value)){
            const key=type.value==='ShortcutAction'?'accelerator':type.value==='LaunchAction'?'target':'command';
            actionInput=el(['CommandAction','CmdAction','TextAction','ScriptAction'].includes(type.value)?'textarea':'input',{required:'',placeholder:type.value==='ShortcutAction'?'Ctrl+Shift+T':type.value==='LaunchAction'?'文件路径或 https://':''});
            actionInput.value=key==='accelerator'?accelerator(value[key]):value[key]||'';
        }else actionInput=null;
        if(actionInput)actionBox.appendChild(field(type.value==='ShortcutAction'?'快捷键':type.value==='WindowAction'?'窗口动作':type.value==='LaunchAction'?'目标':'内容',actionInput));
    }
    type.addEventListener('change',actionFields);actionFields();
    showDialog(gesture?'编辑手势':'添加手势',[field('名称',name),field('触发按钮',trigger),field('方向',result),el('div',{class:'secondary-text',text:'左键绘制手势，或点击方向按钮。'}),draw,tools,field('动作类型',type),actionBox],async()=>{
        if(!directionValues.length)throw new Error('请选择或绘制手势方向。');
        const action={type:type.value};if(actionInput){const key=type.value==='ShortcutAction'?'accelerator':type.value==='WindowAction'?'operation':type.value==='LaunchAction'?'target':'command';action[key]=actionInput.value;}
        await mutate('gestureSave',{profileId,id:gesture?gesture.id:null,name:name.value.trim(),button:trigger.value,directions:directionValues,action});
    });
}
function renderProfiles(root){
    root.appendChild(el('div',{class:'toolbar'},[el('span',{class:'secondary-text',text:'应用配置优先于全局手势。'}),button('＋ 添加应用',()=>editProfile(), 'primary')]));
    const list=el('div',{class:'list'});root.appendChild(list);
    state.profiles.filter(p=>p.id!=='global').forEach((p,index,all)=>{
        const actions=el('div',{class:'item-actions'});
        if(state.capabilities.reorder){const up=itemAction('上移 '+p.name,'↑',()=>mutate('profileMove',{id:p.id,delta:-1}));up.disabled=index===0;const down=itemAction('下移 '+p.name,'↓',()=>mutate('profileMove',{id:p.id,delta:1}));down.disabled=index===all.length-1;actions.append(up,down);}
        actions.append(button('编辑',()=>editProfile(p)),itemAction('删除 '+p.name,'×',()=>confirmDialog('删除应用配置','删除“'+p.name+'”及其手势？',()=>mutate('profileDelete',{id:p.id}))));
        list.appendChild(el('article',{class:'gesture-item'},[el('div',{class:'profile-icon',text:'▦','aria-hidden':'true'}),el('div',{class:'item-main'},[el('div',{class:'item-title',text:p.name}),el('div',{class:'item-detail',text:(p.enabled?'已启用':'已停用')+' · '+p.gestures.length+' 个手势'+(p.inheritGlobal?' · 继承全局':'')}),el('div',{class:'item-detail',text:(p.matchers||[]).map(m=>m.value).join(' · ')||p.legacyExecutablePath||'未绑定应用'})]),actions]));
    });
    if(!list.children.length)list.appendChild(el('div',{class:'empty',text:'为指定应用设置独立手势。'}));
}
function editProfile(profile){
    const name=el('input',{value:profile?profile.name:'',required:'',maxlength:'120'});
    const enabled=el('input',{type:'checkbox'});enabled.checked=!profile||profile.enabled;
    const inherit=el('input',{type:'checkbox'});inherit.checked=!profile||profile.inheritGlobal;
    const fields=[field('名称',name),el('label',{class:'toggle-line'},[enabled,el('span',{text:'启用此应用配置'})]),el('label',{class:'toggle-line'},[inherit,el('span',{text:'继承全局手势'})])];
    const inputs={};state.capabilities.matchers.forEach(key=>{const found=profile&&(profile.matchers||[]).find(m=>m.type===key);const input=el('input',{value:found?found.value:'',placeholder:key==='executable'?'C:\\Program Files\\…':'可留空'});inputs[key]=input;fields.push(field(matcherNames[key],input));});
    showDialog(profile?'编辑应用配置':'添加应用配置',fields,async()=>{const matchers=Object.entries(inputs).filter(([,n])=>n.value.trim()).map(([type,n])=>({type,value:n.value.trim()}));if(!matchers.length)throw new Error('请填写至少一个应用匹配条件。');await mutate('profileSave',{id:profile?profile.id:null,name:name.value.trim(),enabled:enabled.checked,inheritGlobal:inherit.checked,matchers});});
}
function renderBackup(root){
    root.appendChild(section('配置迁移',[
        el('div',{class:'setting-row'},[el('div',{},[el('div',{class:'setting-label',text:'导出跨平台配置'}),el('div',{class:'setting-description',text:'保存当前所选应用的手势为 .cgestures。'})]),button('导出…',async()=>{const result=await rpc('export',{profileId});if(result&&result.message)report('导出结果',result.message);})]),
        el('div',{class:'setting-row'},[el('div',{},[el('div',{class:'setting-label',text:'导入配置'}),el('div',{class:'setting-description',text:'预览兼容性后合并；同名触发手势由导入内容替换。'})]),button('选择文件…',async()=>{const result=await rpc('importPreview');if(!result)return;showDialog('导入预览',[el('div',{class:'report',text:result.message})],async()=>{await mutate('importApply',{token:result.token});},'合并导入');})]),
    ]));
    root.appendChild(el('p',{class:'note',text:'当前导出范围：'+currentProfile().name+'。中键面板配置独立保存。'}));
    if(state.capabilities.fullBackup)root.appendChild(section('Windows 完整备份',[el('div',{class:'setting-row'},[el('div',{},[el('div',{class:'setting-label',text:'包含 Windows 专属动作'}),el('div',{class:'setting-description',text:'使用原有 .wgb 备份与恢复。'})]),button('打开…',async()=>{await rpc('legacy');setState(await rpc('snapshot'));render();})])]));
    root.appendChild(section('恢复',[el('div',{class:'setting-row'},[el('div',{},[el('div',{class:'setting-label',text:'恢复默认手势'}),el('div',{class:'setting-description',text:'替换全局手势和应用配置，常规设置不变。'})]),button('恢复默认值',()=>confirmDialog('恢复默认手势','当前手势和应用配置将被默认配置替换。建议先导出需要保留的配置。',()=>mutate('reset',{})),'danger')])]));
}
function report(title,message){showDialog(title,[el('div',{class:'report',text:message})],async()=>{},'完成');}
function render(){if(!state)return;$('#page-title').textContent=titles[page];document.querySelectorAll('[data-page]').forEach(n=>{n.classList.toggle('active',n.dataset.page===page);n.setAttribute('aria-current',n.dataset.page===page?'page':'false');});const root=$('#content');root.replaceChildren();({general:renderGeneral,gestures:renderGestures,profiles:renderProfiles,backup:renderBackup})[page](root);}
document.querySelectorAll('[data-page]').forEach(n=>n.addEventListener('click',()=>{page=n.dataset.page;render();}));
$('#dialog-close').addEventListener('click',closeDialog);$('#dialog-cancel').addEventListener('click',closeDialog);
$('#dialog-form').addEventListener('submit',async event=>{event.preventDefault();$('#dialog-save').disabled=true;$('#dialog-error').textContent='';try{await dialogSubmit();closeDialog();}catch(error){$('#dialog-error').textContent=error.message;}finally{$('#dialog-save').disabled=false;}});
document.addEventListener('keydown',event=>{
    if($('#modal').hidden)return;
    if(event.key==='Escape'){event.preventDefault();closeDialog();}
    if(event.key==='Tab'){const nodes=Array.from($('#modal').querySelectorAll('button:not(:disabled),input,select,textarea,[tabindex="0"]')).filter(n=>n.offsetParent!==null);const first=nodes[0],last=nodes[nodes.length-1];if(event.shiftKey&&document.activeElement===first){event.preventDefault();last.focus();}else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus();}}
});
rpc('snapshot').then(async value=>{await document.fonts.ready;setState(value);render();}).catch(error=>{$('#content').replaceChildren(el('div',{class:'empty',text:error.message}));$('#runtime-status').textContent='设置连接失败';});

window.addEventListener('focus', async () => {
    if (!state || busy || !$('#modal').hidden) return;
    const previous = state.revision;
    try {
        const latest = await rpc('snapshot');
        if (!busy && $('#modal').hidden && state.revision === previous && latest.revision !== previous) {
            setState(latest); render();
        }
    } catch (error) { toast(error.message); }
});
