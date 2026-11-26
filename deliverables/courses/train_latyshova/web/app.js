'use strict';
const $ = id => document.getElementById(id);
const layer = JSON.parse($('layer').textContent);
const {chapter, glossary = [], tasks = [], cards = []} = layer;
const latyshovaDraftTitles = {
  'part0-1': 'Что определяют по диаграммам ГИС',
  'part0-2': 'Выбор комплекса ГИС и бурение на глинистом растворе',
  'part0-3': 'Бурение на воде и углеводородных растворах',
  'part0-4': 'Типы разрезов и порового пространства',
  'part0-5': 'Практика выбора комплекса ГИС',
  'part0-6': 'Границы пластов и определение литологии',
  'part1-1': 'Глинистость, загипсованность и литологическая колонка',
  'part1-2': 'Прямые признаки терригенного коллектора',
  'part1-3': 'Косвенные признаки и критическая проницаемость',
  'part1-4': 'Выделение коллектора по пористости и глинистости',
  'part1-5': 'Оценка насыщения по сопротивлению',
  'part1-6': 'Палетка для оценки характера насыщения',
  'part2-1': 'Определение критических параметров коллектора',
  'part2-2': 'Границы двухфазного насыщения',
  'part2-3': 'Практика определения критических параметров',
  'part2-4': 'Насыщение и границы продуктивных пластов',
  'part2-5': 'Повторный каротаж и положение контактов',
  'part2-6': 'Эффективная толщина пачки по сопротивлению',
  'part2-7': 'Расчёт толщины пачки с плотными прослоями',
  'part3-1': 'Практика расчёта эффективной толщины',
  'part3-2': 'Выделение карбонатных коллекторов',
  'part3-3': 'Нормализация каротажных диаграмм',
  'part3-4': 'Критическая пористость по рис. 77',
  'part3-5': 'Задачи 104–107 по коллекторам',
  'part3-6': 'Задача 108. Нижний предел пористости'
};
const nodes = layer.nodes.map(node => {
  if (chapter.built_with?.model !== 'mock') return node;
  const title = chapter.id === 'latyshova' && latyshovaDraftTitles[node.id.split('.').at(-1)];
  if (title) return {...node, title};
  if (node.book_title && node.book_title.toLowerCase().startsWith(node.title.toLowerCase())
      && node.book_title.length > node.title.length) return {...node, title: node.book_title};
  return node;
}).sort((a,b) => a.order-b.order);
const nodeById = new Map(nodes.map(node => [node.id, node]));
const relations = nodes.flatMap(from => (from.links || [])
  .map(link => ({from, to: nodeById.get(link.to), type: link.type})).filter(edge => edge.to));
const spaceId = layer.space_id;
const key = 'geocourse.v1.' + chapter.id;
let state = {node:nodes[0]?.id, done:[], cards:{}, notes:{}};
try { Object.assign(state, JSON.parse(localStorage.getItem(key)) || {}); } catch {}
state.done = [...new Set(Array.isArray(state.done) ? state.done.filter(id => nodeById.has(id)) : [])];
const linkedStep = new URLSearchParams(location.search).get('step');
let current = nodes.find(n => n.id === linkedStep) || nodes.find(n => n.id === state.node) || nodes[0];
let view = 'lesson';
const content = $('content');
function save() {
  try { localStorage.setItem(key,JSON.stringify(state)); return true; } catch { return false; }
}
function add(parent, tag, text='', cls='') {
  const e=document.createElement(tag);
  e.textContent=text;
  if(cls) e.className=cls;
  parent.append(e);
  return e;
}
function button(parent,label,fn,cls='') {
  const b=add(parent,'button',label,cls);
  b.type='button'; b.onclick=fn;
  return b;
}
function details(parent,title,cls='') {
  const d=add(parent,'details','',cls);
  add(d,'summary',title);
  return d;
}
function localPath(path) {
  return typeof path==='string' && !/[:\\]/.test(path) && !path.startsWith('/') && !path.split('/').includes('..');
}
function pdfPage(page){ return Number(page) - (Number(chapter.pdf_first_page) || 1) + 1; }
function source(parent,page,label='стр. '+page) {
  if (!page) return;
  const hasPDF=chapter.pdf && localPath(chapter.pdf);
  const el=add(parent,hasPDF?'a':'span',label,'ref');
  if(hasPDF){el.href=chapter.pdf+'#page='+pdfPage(page);el.target='_blank';el.rel='noopener';}
}
function math(parent,latex,block=false) {
  const display = latex.match(/^\s*(\\{1,2}\[|\$\$)([\s\S]*?)(?:\\{1,2}\]|\$\$)\s*$/);
  const formula = display ? display[2].replaceAll('\\\\', '\\') : latex;
  const displayMode = block || Boolean(display) || /\\tag\b/.test(formula);
  const span=add(parent,'span',formula);
  if(window.katex) katex.render(formula,span,{displayMode,throwOnError:false,trust:false,strict:'ignore'});
}
function rich(parent,text) {
  const pieces = String(text ?? '').split(/(\[\[.*?\]\]|\\{1,2}\([\s\S]*?\\{1,2}\)|\\{1,2}\[[\s\S]*?\\{1,2}\]|\$\$[\s\S]+?\$\$|\$(?!\s)[^$\n]+?\$)/g);
  pieces.forEach((part, i) => {
    if (i % 2 === 0) { parent.append(part); return; }
    if (part.startsWith('[[')) {
      const [id,label]=part.slice(2,-2).split('|');
      const term=glossary.find(t=>t.id===id);
      if(term){
        const abbr=add(parent,'abbr',label || term.term,'term');
        abbr.title=term.definition;
      }else parent.append(label || id);
    } else {
      const delimiter = part.match(/^(?:\\{1,2}[(\[]|\${1,2})/)[0];
      const endLength = delimiter.startsWith('$') ? delimiter.length : part.match(/\\{1,2}[)\]]$/)[0].length;
      const formula = part.slice(delimiter.length, -endLength);
      math(parent, delimiter.startsWith('\\\\') ? formula.replaceAll('\\\\', '\\') : formula, delimiter.endsWith('[') || delimiter === '$$');
    }
  });
}
function bookText(parent, tag, text, cls) {
  const el = add(parent, tag, '', cls);
  rich(el, text);
  return el;
}
function stepButton(parent, node, cls) {
  const control = button(parent, '', () => openNode(node.id), cls);
  rich(control, node.order + '. ' + node.title);
  return control;
}
const kinds={observation:'Наблюдение',inference:'Вывод',assumption:'Допущение'};
function evidence(parent,claim){
  if (claim.verified === false) add(parent, 'small', 'Не проверено', 'qualityBadge');
  bookText(parent,'blockquote',claim.quote);
  parent.append((kinds[claim.kind] || '')+' · '); source(parent,claim.page);
}
function paragraphs(parent,items,node=current){
  for(const p of items || []){
    if (chapter.built_with?.model === 'mock' && /^KEYWORDS:.*----\s*$/s.test(p.text)) continue;
    const para=add(parent,p.by==='author'?'blockquote':'p');
    rich(para,p.text);
    const claims=(p.claims || []).map(id=>node.claims.find(c=>c.id===id)).filter(Boolean);
    const meta=add(parent,'div','','muted');
    if (p.by === 'author' || claims.length) source(meta, p.page);
    const origin = p.by === 'author' ? 'Цитата автора' : claims.length ? 'Пересказ модели' : 'Текст модели без ссылки на книгу';
    add(meta, 'small', origin, 'paragraphOrigin');
    if(claims.some(c=>c.verified === false)) add(meta,'small','Не проверено','qualityBadge');
    if(claims.length){
      const d=details(meta,'Основание в книге','evidence');
      claims.forEach(c=>evidence(d,c));
    }
  }
}
function section(parent,title,items,draw){
  if(!items?.length) return;
  add(parent,'h3',title); items.forEach(x=>draw(parent,x));
}
function openNode(id){
  if (!nodes.length || examRunning()) return;
  current=nodes.find(n=>n.id===id) || current;
  state.node=current.id;save(); openView('lesson');
}
function openView(name){
  if (examRunning() && name !== 'exam') return;
  showWorkspace(false);
  panel('read');
  if (view !== name || name === 'lesson') {
    view = name;
    render();
  }
  $('reader').focus();
}
const views = {
  lesson: 'Урок', practice: 'Тесты', cards: 'Карточки', summary: 'Конспект',
  map: 'Карта связей', terms: 'Словарь', lab: 'Виртуальная лаборатория',
  progress: 'Прогресс', exam: 'Экзамен'
};
function renderLesson(){
  const n=current;
  add(content,'small','Шаг '+(nodes.indexOf(n)+1)+' / '+nodes.length+(n.minutes ? ' · '+n.minutes+' мин' : ''),'kicker');
  rich(add(content,'h2'),n.title);
  if (n.fallback || chapter.built_with?.model === 'mock') add(content, 'small', 'Черновик', 'qualityBadge');
  rich(add(content,'small','','muted'), n.book_title);
  if (chapter.pdf && chapter.id === 'latyshova') {
    if (n.id === 'latyshova.part3-4' || n.id === 'latyshova.carbonate-cutoff-porosity') {
      source(content, 107, 'Рис. 77 · стр. 107');
    }
    if (['latyshova.part3-5', 'latyshova.part3-6'].includes(n.id)) {
      source(content, 108, 'Таблица 23 · стр. 108');
    }
  }
  if(n.summary?.length){
    const lead=add(content,'section','','lead');add(lead,'h3','Суть');paragraphs(lead,n.summary);
  }
  if(n.term_ids?.length) {
    n.term_ids.map(id=>glossary.find(t=>t.id===id)).filter(Boolean).forEach(t=>{
      const p=add(content,'p');bookText(p,'strong',t.term+' — ');rich(p,t.definition);
    });
  }
  for(const [field,title] of [['how_it_works','Как это работает'],['steps','По шагам'],['numbers','Цифры и условия'],['now_practice','Современная практика']]){
    if(n[field]?.length){add(content,'h3',title);paragraphs(content,n[field]);}
  }
  section(content,'Разбор примеров',n.examples,(p,x)=>{
    const d=add(p,'div','','box');bookText(d,'h4',x.title);source(d,x.page);
    if(x.figure)d.append(' · '+x.figure);
    for(const [k,title] of [['condition','Условие'],['solution','Решение'],['result','Результат']])
      if(x[k]?.length){add(d,'strong',title);paragraphs(d,x[k]);}
  });
  section(content,'Формулы',n.formulas,(p,f)=>{
    const d=add(p,'div','','math');math(d,f.latex);source(p,f.page);
    for(const v of f.vars || []){const line=add(p,'p');math(line,v.sym);line.append(' — '+v.meaning+' ('+v.unit+')');}
  });
  section(content,'Таблицы',n.tables,(p,t)=>{
    bookText(p,'strong',t.caption);source(p,t.page);
    const table=add(add(p,'div','','table-scroll'),'table');
    let header=true;
    for(const row of t.markdown.trim().split('\n')){
      if(/^\s*\|?[\s|:-]+\|?\s*$/.test(row))continue;
      const tr=add(table,'tr');
      row.trim().replace(/^\||\|$/g,'').split('|').forEach(cell=>rich(add(tr,header?'th':'td'),cell.trim()));
      header=false;
    }
    (t.ocr_fixes||[]).forEach(f=>add(p,'small',f));
  });
  if(n.misconception){add(content,'h3','Частая ошибка');bookText(content,'p',n.misconception.wrong);paragraphs(content,n.misconception.right);}
  dataMeaning(content,n);
  if(n.analogy){add(content,'h3','Аналогия');bookText(content,'p',n.analogy.text);bookText(content,'p','Граница аналогии · '+n.analogy.breaks_where);}
  for(const [k,title] of [['mechanism','Механизм'],['practice','Практика специалиста'],['nuances','Нюансы'],['deeper','Глубже']])
    if(n.layers?.[k]?.length)paragraphs(details(content,title),n.layers[k]);
  section(content,'Задачи книги',n.book_tasks,(p,t)=>{if(t.ocr_bad)add(p,'strong','Сверить по скану','warning');bookText(p,'p','№ '+t.number+' · '+t.text);if(t.figure)p.append(t.figure+' · ');source(p,t.page);});
  for (const illustration of n.illustrations || []) {
    if (!illustration.src?.endsWith('-links.svg')) drawIllustration(content, illustration);
  }
  const links = details(content, 'Связи шага');
  showRelations(links, n);
  section(content,'Проверь себя',tasks.filter(t=>t.node_id===n.id),quiz);
  if (service?.laboratory && serverSources().length) {
    const entry = button(content, 'Исследовать образец по теме', openCourseLab);
    entry.hidden = true;
    labPost('recommend', {source: labSource(), node: n.id}).then(r => { entry.hidden = !r.available; }).catch(() => {});
  }
  const row=add(content,'div','','navrow');
  const done=state.done.includes(n.id);
  button(row,done?'Пройдено ✓':'Отметить пройденным',()=>{state.done.push(n.id);save();render();},'primary').disabled=done;
  const next=nodes[nodes.indexOf(n)+1];if(next)button(row,'Следующий шаг',()=>openNode(next.id));
}
function drawIllustration(parent, illustration) {
  if (!localPath(illustration.src)) return;
  const figure = add(parent, 'figure');
  const alt = illustration.alt || illustration.caption || '';
  const realData = illustration.class === 'A';
  const opener = realData && button(figure, '', () => openIllustration(illustration.src, alt), 'illustrationOpener');
  if (opener) opener.setAttribute('aria-label', 'Увеличить: ' + (alt || 'иллюстрация'));
  const image = add(opener || figure, 'img');
  image.src = illustration.src;
  image.alt = alt;
  add(figure, 'figcaption', [
    illustration.caption, illustration.provenance,
    illustration.redrawn_from && 'Перерисовано по ' + illustration.redrawn_from
  ].filter(Boolean).join(' · '));
}
function openIllustration(src, alt) {
  const dialog = add(document.body, 'dialog', '', 'illustrationDialog');
  dialog.setAttribute('aria-label', alt || 'Иллюстрация');
  const close = button(dialog, 'Закрыть ×', () => dialog.close(), 'illustrationClose');
  specimenViewer(dialog, {media_url: src, alt}, undefined, undefined, {inlineImage: true});
  dialog.addEventListener('click', event => { if (event.target === dialog) dialog.close(); });
  dialog.addEventListener('close', () => dialog.remove(), {once: true});
  dialog.showModal();
  close.focus();
}
function dataMeaning(parent,n){
  const d=n.data_meaning;if(!d)return;
  add(parent,'h3','Что это значит для данных');
  if(d.input)bookText(parent,'p','Входные данные · '+d.input);
  if(d.output)bookText(parent,'p','Результат · '+d.output);
  paragraphs(parent,d.breaks,n);paragraphs(parent,d.hypotheses,n);
}
const normalize=v=>String(v).trim().toLocaleLowerCase('ru').replace(/\s+/g,' ');
function quiz(parent,t,exam=false){
  const box=add(parent,'div','','box');rich(add(box,'strong'),t.question);
  const inputs=[];
  let answer,check,answered=()=>inputs.length>0 && inputs.every(input=>input.value.trim());
  let snapshot = () => inputs.map(input => input.type === 'radio' || input.type === 'checkbox' ? input.checked : input.value);
  let restore = values => inputs.forEach((input, index) => {
    if (input.type === 'radio' || input.type === 'checkbox') input.checked = values[index] === true;
    else input.value = values[index] ?? '';
  });
  if(['single','multi'].includes(t.type)){
    t.options.forEach((v,i)=>{
      const label=add(box,'label','','choice');
      const field=add(label,'input');field.type=t.type==='single'?'radio':'checkbox';field.name=t.id;rich(label,v);inputs.push(field);
    });
    answered=()=>inputs.some(input=>input.checked);
    const correct=[].concat(t.answer).sort((a,b)=>a-b);
    answer=correct.map(i=>t.options[i]).join(', ');
    check=()=>JSON.stringify(inputs.flatMap((e,i)=>e.checked?[i]:[]))===JSON.stringify(correct);
  }else if(t.type==='cloze'){
    const line=add(box,'p');
    for(const part of t.text.split(/(\{\{\d+\}\})/)){
      if(!part.startsWith('{{')){rich(line,part);continue;}
      const index=Number(part.slice(2,-2))-1;
      const e=add(line,'input');e.size=6;e.setAttribute('aria-label','Пропуск '+(index+1));inputs[index]=e;
    }
    answer=t.answers.map(v=>v[0]).join(', ');
    check=()=>t.answers.every((vs,i)=>vs.map(normalize).includes(normalize(inputs[i]?.value || '')));
  }else if(t.type==='calc'){
    const label=add(box,'label','Ответ ('+t.unit+') ');
    const input=add(label,'input');inputs.push(input);input.inputMode='decimal';
    answer=t.answer+' '+t.unit;
    check=()=>{const s=input.value.trim().replace(',','.');return /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$/.test(s)&&Math.abs(Number(s)-t.answer)<=t.tolerance+1e-10;};
  }else if(t.type==='order'){
    const list=add(box,'div');let items=t.items.map((_,i)=>(i+1)%t.items.length);
    let moved = false;
    answered=()=>moved || items.length === 1;
    snapshot=()=>moved ? [...items] : null;
    restore=values=>{
      moved=values?.length === items.length;
      items=moved ? [...values] : t.items.map((_,i)=>(i+1)%t.items.length);
      draw();
    };
    function move(from,to){if(to<0 || to>=items.length || from===to)return;moved=true;items.splice(to,0,items.splice(from,1)[0]);draw();box.dispatchEvent(new Event('input', {bubbles:true}));}
    function draw(){
      list.replaceChildren();items.forEach((id,i)=>{
        const row=add(list,'div','','orderRow');row.dataset.index=i;
        const handle=button(row,'⠿',()=>{},'handle');handle.setAttribute('aria-label','Перетащить '+t.items[id]);
        handle.onpointerdown=e=>handle.setPointerCapture(e.pointerId);
        handle.onpointerup=e=>{const target=document.elementFromPoint(e.clientX,e.clientY)?.closest('.orderRow');if(target && list.contains(target))move(i,Number(target.dataset.index));};
        bookText(row,'span',t.items[id]);
        for(const [dir,delta] of [['Выше',-1],['Ниже',1]]){
          const b=button(row,delta<0?'↑':'↓',()=>{move(i,i+delta);list.children[i+delta]?.querySelector('button')?.focus();});
          b.setAttribute('aria-label',dir+' · '+t.items[id]);b.disabled=i+delta<0 || i+delta>=items.length;
        }
      });
    }
    draw();answer=t.items.join(' → ');check=()=>items.every((v,i)=>v===i);
  }else return;
  if (exam) return {check, answered, answer, snapshot, restore};
  const out=add(box,'output');out.setAttribute('aria-live','polite');
  button(box,'Проверить',()=>{out.replaceChildren();rich(out,(check()?'Верно. ':'Верный ответ — '+answer+'. ')+t.explanation);},'primary');
  if (t.citation) {
    const ref = details(box, t.citation.source + ' · стр. ' + t.citation.page);
    bookText(ref, 'blockquote', t.citation.quote);
  }
  const n=nodes.find(n=>n.id===t.node_id);
  if(n && view!=='lesson')button(box,'К шагу',()=>openNode(n.id));
  const c=n?.claims?.find(c=>c.id===t.claim_id);
  if(c)evidence(details(box,'Основание ответа','evidence'),c);
}
function renderStudy(){
  add(content,'h2',views[view]);
  if (view === 'practice') {
    renderPractice();
  }
  if (view === 'lab') {
    renderLabWorkspace(content);
  }
  if (view === 'progress') {
    if (nodes.length) add(content, 'p', 'Пройдено ' + nodes.filter(node => state.done.includes(node.id)).length + ' из ' + nodes.length + ' шагов.');
    if (nodes.length) add(content, 'p', 'Отмечено как знакомые: ' + cards.filter(card => state.cards[card.id] === 'Знаю').length + ' из ' + cards.length + ' карточек.');
    add(content, 'p', 'Зачтено лабораторных работ: ' + Object.keys(state.labPassed || {}).length);
    const list = add(content, 'ul');
    for (const node of nodes) {
      const item = add(list, 'li');
      stepButton(item, node);
      if (state.done.includes(node.id)) add(item, 'small', ' · Пройдено');
    }
  }
  if (view === 'exam') renderExam();
  if(view==='cards')for(const c of cards){
    const box=add(content,'section','','box');const original=layer.nodes.find(n=>n.id===c.node_id);
    bookText(box,'strong',original && c.front===original.title ? nodeById.get(c.node_id).title : c.front);
    bookText(details(box,'Показать ответ'),'p',c.back);
    for(const choice of ['Знаю','Повторить']){
      const b=button(box,choice,()=>{state.cards[c.id]=choice;save();render();});
      b.setAttribute('aria-pressed',state.cards[c.id]===choice);
      if(state.cards[c.id]===choice)b.className='primary';
    }
  }
  if(view==='terms' && !glossary.length) add(content,'p','В этой сборке главы словарь пока пуст.');
  if(view==='terms')for(const t of glossary){
    add(content,'h3',t.term);add(content,'small',t.en);bookText(content,'p',t.definition);source(content,t.page);
    button(content,'К шагу',()=>openNode(t.node_id));
  }
  if(view==='summary'){
    button(content,'Печать / PDF',()=>window.print());
    for(const n of nodes){bookText(content,'h3',n.title);paragraphs(content,n.summary,n);dataMeaning(content,n);}
  }
  if(view==='map')drawGraph();
  if(view==='map')for(const n of nodes){
    const box=add(content,'section','','box');stepButton(box,n,'primary');
    showRelations(box,n);
  }
}
function renderLab() {
  const simulations = nodes.flatMap(node => (node.illustrations || [])
    .filter(illustration => illustration.provenance === 'симуляция' && localPath(illustration.src))
    .map(illustration => ({ node, illustration })));
  if (!simulations.length) {
    return;
  }
  add(content, 'p', 'Рассмотри готовую симуляцию из главы и открой соответствующий урок.');
  const label = add(content, 'label', 'Симуляция ');
  const select = add(label, 'select');
  for (const { node, illustration } of simulations) add(select, 'option', illustration.caption || node.title);
  const preview = add(content, 'div', '', 'simulation');
  function update() {
    const { node, illustration } = simulations[select.selectedIndex];
    preview.replaceChildren();
    drawIllustration(preview, illustration);
    button(preview, 'Открыть урок', () => openNode(node.id));
  }
  select.onchange = update;
  update();
}

const cleanHeading = text => text.toLowerCase().replace(/[_\s]/g, '');
const relationLabels = {
  prerequisite: ['Опирается на', 'Нужен для'],
  example: ['Пример для', 'Пример приведён в'],
  refutes_misconception: ['Опровергает заблуждение из', 'Заблуждение разобрано в'],
  to_data: ['Переход к данным', 'К этому шагу ведёт']
};
function showRelations(parent, node) {
  const edges = relations.filter(edge => edge.from === node || edge.to === node);
  if (!edges.length) add(parent, 'p', 'В материалах главы связи для этого шага не указаны.', 'muted');
  for (const edge of edges) {
    const outgoing = edge.from === node;
    const labels = relationLabels[edge.type] || ['Связан с', 'Связан с'];
    const row = add(parent, 'div', labels[outgoing ? 0 : 1] + ' ', 'stepRelation');
    stepButton(row, outgoing ? edge.to : edge.from);
  }
}

let graphObserver;
function drawGraph(){
  add(content, 'p', 'Шагов: ' + nodes.length + ' · Связей в материалах главы: ' + relations.length);
  const graph = add(content, 'div', '', 'courseGraph');
  const svg = document.createElementNS('http://www.w3.org/2000/svg','svg');
  svg.setAttribute('aria-hidden','true');
  graph.append(svg);
  const rows = new Map(nodes.map(node => [node, stepButton(graph, node, 'graphStep')]));
  function connect() {
    svg.replaceChildren();
    for (const {from, to} of relations) {
      const start = rows.get(from), end = rows.get(to);
      const y = start.offsetTop + start.offsetHeight/2, z = end.offsetTop + end.offsetHeight/2;
      const bend = Math.max(1, 27 - Math.abs(from.order-to.order)*3);
      const path = document.createElementNS(svg.namespaceURI, 'path');
      path.setAttribute('d', 'M 42 '+y+' C '+bend+' '+y+', '+bend+' '+z+', 42 '+z);
      svg.append(path);
    }
  }
  graphObserver = new ResizeObserver(connect);
  for (const row of rows.values()) graphObserver.observe(row);
  connect();
}

function render(){
  graphObserver?.disconnect();
  const takingExam = examRunning();
  $('showChat').disabled = $('showLesson').disabled = $('query').disabled = takingExam;
  $('search').querySelector('button').disabled = takingExam;
  $('route').replaceChildren();
  for(const part of layer.parts){
    const members=nodes.filter(n=>n.part_id===part.id);
    const canonical=members.find(n=>n.book_title && cleanHeading(n.book_title)===cleanHeading(part.title));
    bookText($('route'),'div',canonical?.book_title || part.title,'part');
    for(const n of members){
      const b=stepButton($('route'),n,'routeBtn');
      if(state.done.includes(n.id)) b.prepend('✓ ');
      b.disabled = takingExam;
      if(n===current)b.setAttribute('aria-current','step');
    }
  }
  $('progress').hidden = $('progressLabel').hidden = !nodes.length;
  $('progress').max=nodes.length || 1;$('progress').value=state.done.length;
  $('progressLabel').textContent='Пройдено '+state.done.length+' из '+nodes.length;
  $('toolbar').replaceChildren();
  const toolbarGroup = add($('toolbar'), 'div', '', 'toolbarGroup');
  add(toolbarGroup, 'strong', views[view]);
  if (view !== 'lesson' && !takingExam) button(toolbarGroup, 'К уроку', () => openView('lesson'));
  if (['practice', 'lab', 'exam'].includes(view)) {
    const expand = button($('toolbar'), '', () => toggleExpanded(expand));
    syncExpanded(expand);
  } else {
    delete $('workspace').dataset.expanded;
  }
  $('tools').replaceChildren();
  const activities = [
    ['summary','≡'], ['cards','▤'], ['practice','?'], ['map','⌘'],
    ['lab','◇'], ['progress','◫'], ['exam','✓'], ['terms','А']
  ];
  if (spaceId) add($('tools'), 'p', serverSources().length
    ? 'Загруженные материалы доступны в чате, тестах и лаборатории.'
    : 'Добавьте источник, чтобы начать практику.', 'muted');
  for (const [id, icon] of activities.filter(([id]) => nodes.length || ['lab', 'progress', 'practice', 'exam'].includes(id))) {
    const control = button($('tools'), '', () => openView(id), 'toolBtn');
    control.disabled = takingExam && id !== 'exam';
    add(control, 'b', icon).setAttribute('aria-hidden', 'true');
    add(control, 'span', views[id]);
    control.setAttribute('aria-pressed', view === id);
  }
  updateChatContext();
  if (current) {
    $('note').value=state.notes[current.id] || '';
    $('saved').textContent='К шагу «'+current.title+'»';
  }
  content.replaceChildren();
  if (view !== 'lesson') renderStudy();
  else if (current) renderLesson();
  else {
    add(content, 'h2', serverSources().length ? 'Материалы готовы к работе' : 'Добавьте первый источник');
    add(content, 'p', serverSources().length
      ? 'Откройте документ в панели источников или задайте вопрос тьютору.'
      : 'Загрузите PDF, DOCX, TXT или Markdown. Файлы можно организовать по папкам.');
    button(content, serverSources().length ? 'Открыть чат' : 'Добавить источник', () => {
      if (serverSources().length) showWorkspace(true);
      else $('addSource').click();
    }, 'primary');
  }
}
$('note').oninput=e=>{state.notes[current.id]=e.target.value;$('saved').textContent=save()?'Заметка сохранена на устройстве':'Заметка доступна до закрытия вкладки';};
const searchWords = text => String(text || '').toLocaleLowerCase('ru').replaceAll('ё', 'е').match(/[\p{L}\p{N}]+/gu) || [];
const searchText = value => typeof value === 'string' || typeof value === 'number' ? String(value)
  : value && typeof value === 'object' ? Object.values(value).map(searchText).join(' ') : '';
const searchableNodes = nodes.map(node => ({
  node, words: searchWords(searchText(node) + ' ' + searchText(glossary.filter(term => term.node_id === node.id)))
}));
let searchRun = 0;
$('search').onsubmit = async event => {
  event.preventDefault();
  const query = $('query').value.trim();
  const tokens = searchWords(query);
  const results = $('results');
  results.replaceChildren();
  const run = ++searchRun;
  if (!tokens.length) return;
  const matches = words => tokens.every(token => words.some(word => word.startsWith(token)
    || token.length >= 6 && word.slice(0, 6) === token.slice(0, 6)));
  for (const {node, words} of searchableNodes.filter(row => matches(row.words))) {
    const item = add(results, 'div', '', 'searchHit');
    stepButton(item, node);
    const term = glossary.find(term => term.node_id === node.id && matches(searchWords(searchText(term))));
    if (term) bookText(item, 'p', term.term + ' — ' + term.definition);
    else source(item, node.pages?.[0]);
  }
  if (service) {
    try {
      const {hits} = await api('search?q=' + encodeURIComponent(query), null, 5000);
      if (run !== searchRun) return;
      for (const hit of hits) {
        const item = add(results, 'div', '', 'searchHit');
        const link = add(item, 'a', hit.chapter + (hit.page ? ' · стр. ' + hit.page : ''));
        link.href = apiBase + '/' + encodeURIComponent(hit.folder) + '/index.html'
          + (hit.node ? '?step=' + encodeURIComponent(hit.node) : '');
        bookText(item, 'p', hit.text);
      }
    } catch {
      if (run === searchRun) add(results, 'p', 'Поиск по каталогу недоступен.', 'muted');
    }
  }
  if (run === searchRun && !results.childElementCount) add(results, 'p', 'По этому запросу ничего не найдено.');
};
$('title').textContent=chapter.title_short || chapter.title;
document.title=$('title').textContent + ' · QABAT';
$('author').textContent=[chapter.author, chapter.year].filter(Boolean).join(' · ');
$('meta').textContent=spaceId ? 'Учебное пространство' : nodes.length+' '+({one:'шаг',few:'шага',many:'шагов'}[new Intl.PluralRules('ru').select(nodes.length)])+(nodes.every(n=>n.minutes) ? ' / '+nodes.reduce((total,n)=>total+n.minutes,0)+' мин' : '');
