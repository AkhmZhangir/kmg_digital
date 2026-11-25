'use strict';
const $ = id => document.getElementById(id);
const layer = JSON.parse($('layer').textContent);
const {chapter, glossary = [], tasks = [], cards = []} = layer;
const nodes = [...layer.nodes].sort((a,b) => a.order-b.order);
const spaceId = layer.space_id;
const key = 'geocourse.v1.' + chapter.id;
let state = {node:nodes[0]?.id, done:[], cards:{}, notes:{}};
try { Object.assign(state, JSON.parse(localStorage.getItem(key)) || {}); } catch {}
let current = nodes.find(n => n.id === state.node) || nodes[0];
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
function source(parent,page) {
  if (!page) return;
  const hasPDF=chapter.pdf && localPath(chapter.pdf);
  const el=add(parent,hasPDF?'a':'span','стр. '+page,'ref');
  if(hasPDF){el.href=chapter.pdf+'#page='+pdfPage(page);el.target='_blank';el.rel='noopener';}
}
function math(parent,latex) {
  const span=add(parent,'span',latex);
  if(window.katex) katex.render(latex,span,{throwOnError:false,trust:false,strict:'ignore'});
}
function rich(parent,text) {
  for(const part of String(text || '').split(/(\[\[.*?\]\]|\\\([\s\S]*?\\\))/g)){
    if(part.startsWith('[[')){
      const [id,label]=part.slice(2,-2).split('|');
      const term=glossary.find(t=>t.id===id);
      if(term){
        const abbr=add(parent,'abbr',label || term.term,'term');
        abbr.title=term.definition;
      }else parent.append(label || id);
    }else if(part.startsWith('\\(')) math(parent,part.slice(2,-2));
    else parent.append(part);
  }
}
const kinds={observation:'Наблюдение',inference:'Вывод',assumption:'Допущение'};
function evidence(parent,claim){
  if (claim.verified === false) add(parent, 'small', 'Не проверено', 'qualityBadge');
  add(parent,'blockquote',claim.quote);
  parent.append((kinds[claim.kind] || '')+' · '); source(parent,claim.page);
}
function paragraphs(parent,items,node=current){
  for(const p of items || []){
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
  if (!nodes.length) return;
  current=nodes.find(n=>n.id===id) || current;
  state.node=current.id;save(); openView('lesson');
}
function openView(name){
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
  add(content,'h2',n.title);
  if (n.fallback) add(content, 'small', 'Черновик', 'qualityBadge'); add(content,'small',n.book_title,'muted');
  if(n.summary?.length){
    const lead=add(content,'section','','lead');add(lead,'h3','Суть');paragraphs(lead,n.summary);
  }
  if(n.term_ids?.length) {
    n.term_ids.map(id=>glossary.find(t=>t.id===id)).filter(Boolean).forEach(t=>{
      const p=add(content,'p');add(p,'strong',t.term+' — ');p.append(t.definition);
    });
  }
  for(const [field,title] of [['how_it_works','Как это работает'],['steps','По шагам'],['numbers','Цифры и условия'],['now_practice','Современная практика']]){
    if(n[field]?.length){add(content,'h3',title);paragraphs(content,n[field]);}
  }
  section(content,'Разбор примеров',n.examples,(p,x)=>{
    const d=add(p,'div','','box');add(d,'h4',x.title);source(d,x.page);
    if(x.figure)d.append(' · '+x.figure);
    for(const [k,title] of [['condition','Условие'],['solution','Решение'],['result','Результат']])
      if(x[k]?.length){add(d,'strong',title);paragraphs(d,x[k]);}
  });
  section(content,'Формулы',n.formulas,(p,f)=>{
    const d=add(p,'div','','math');math(d,f.latex);source(p,f.page);
    for(const v of f.vars || []){const line=add(p,'p');math(line,v.sym);line.append(' — '+v.meaning+' ('+v.unit+')');}
  });
  section(content,'Таблицы',n.tables,(p,t)=>{
    add(p,'strong',t.caption);source(p,t.page);
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
  if(n.misconception){add(content,'h3','Частая ошибка');add(content,'p',n.misconception.wrong);paragraphs(content,n.misconception.right);}
  dataMeaning(content,n);
  if(n.analogy){add(content,'h3','Аналогия');add(content,'p',n.analogy.text);add(content,'p','Граница аналогии · '+n.analogy.breaks_where);}
  for(const [k,title] of [['mechanism','Механизм'],['practice','Практика специалиста'],['nuances','Нюансы'],['deeper','Глубже']])
    if(n.layers?.[k]?.length)paragraphs(details(content,title),n.layers[k]);
  section(content,'Задачи книги',n.book_tasks,(p,t)=>{if(t.ocr_bad)add(p,'strong','Сверить по скану','warning');add(p,'p','№ '+t.number+' · '+t.text);if(t.figure)p.append(t.figure+' · ');source(p,t.page);});
  for (const illustration of n.illustrations || []) drawIllustration(content, illustration);
  section(content,'Проверь себя',tasks.filter(t=>t.node_id===n.id),quiz);
  if (service?.laboratory && serverSources().length) {
    const entry = button(content, 'Исследовать образец по теме', () => openView('lab'));
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
  const image = add(figure, 'img');
  image.src = illustration.src;
  image.alt = illustration.alt || illustration.caption || '';
  add(figure, 'figcaption', [
    illustration.caption, illustration.provenance,
    illustration.redrawn_from && 'Перерисовано по ' + illustration.redrawn_from
  ].filter(Boolean).join(' · '));
}
function dataMeaning(parent,n){
  const d=n.data_meaning;if(!d)return;
  add(parent,'h3','Что это значит для данных');
  if(d.input)add(parent,'p','Входные данные · '+d.input);
  if(d.output)add(parent,'p','Результат · '+d.output);
  paragraphs(parent,d.breaks,n);paragraphs(parent,d.hypotheses,n);
}
const normalize=v=>String(v).trim().toLocaleLowerCase('ru').replace(/\s+/g,' ');
function quiz(parent,t,exam=false){
  const box=add(parent,'div','','box');rich(add(box,'strong'),t.question);
  const inputs=[];let answer,check;
  if(['single','multi'].includes(t.type)){
    t.options.forEach((v,i)=>{
      const label=add(box,'label','','choice');
      const field=add(label,'input');field.type=t.type==='single'?'radio':'checkbox';field.name=t.id;rich(label,v);inputs.push(field);
    });
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
    const input=add(label,'input');input.inputMode='decimal';
    answer=t.answer+' '+t.unit;
    check=()=>{const s=input.value.trim().replace(',','.');return /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$/.test(s)&&Math.abs(Number(s)-t.answer)<=t.tolerance+1e-10;};
  }else if(t.type==='order'){
    const list=add(box,'div');const items=t.items.map((_,i)=>(i+1)%t.items.length);
    function move(from,to){if(to<0 || to>=items.length || from===to)return;items.splice(to,0,items.splice(from,1)[0]);draw();}
    function draw(){
      list.replaceChildren();items.forEach((id,i)=>{
        const row=add(list,'div','','orderRow');row.dataset.index=i;
        const handle=button(row,'⠿',()=>{},'handle');handle.setAttribute('aria-label','Перетащить '+t.items[id]);
        handle.onpointerdown=e=>handle.setPointerCapture(e.pointerId);
        handle.onpointerup=e=>{const target=document.elementFromPoint(e.clientX,e.clientY)?.closest('.orderRow');if(target && list.contains(target))move(i,Number(target.dataset.index));};
        add(row,'span',t.items[id]);
        for(const [dir,delta] of [['Выше',-1],['Ниже',1]]){
          const b=button(row,delta<0?'↑':'↓',()=>{move(i,i+delta);list.children[i+delta]?.querySelector('button')?.focus();});
          b.setAttribute('aria-label',dir+' · '+t.items[id]);b.disabled=i+delta<0 || i+delta>=items.length;
        }
      });
    }
    draw();answer=t.items.join(' → ');check=()=>items.every((v,i)=>v===i);
  }else return;
  if (exam) return check;
  const out=add(box,'output');out.setAttribute('aria-live','polite');
  button(box,'Проверить',()=>{out.textContent=(check()?'Верно. ':'Верный ответ — '+answer+'. ')+t.explanation;},'primary');
  const n=nodes.find(n=>n.id===t.node_id);
  if(n && view!=='lesson')button(box,'К шагу',()=>openNode(n.id));
  const c=n?.claims?.find(c=>c.id===t.claim_id);
  if(c)evidence(details(box,'Основание ответа','evidence'),c);
}
function renderStudy(){
  add(content,'h2',views[view]);
  if (view === 'practice') {
    if (!tasks.length) add(content, 'p', 'В этой главе пока нет заданий.');
    tasks.forEach(task => quiz(content, task));
  }
  if (view === 'lab') {
    specimenLab(add(content, 'section'));
    renderLab();
  }
  if (view === 'progress') {
    if (nodes.length) add(content, 'p', 'Пройдено ' + nodes.filter(node => state.done.includes(node.id)).length + ' из ' + nodes.length + ' шагов.');
    if (nodes.length) add(content, 'p', 'Отмечено как знакомые: ' + cards.filter(card => state.cards[card.id] === 'Знаю').length + ' из ' + cards.length + ' карточек.');
    add(content, 'p', 'Зачтено лабораторных работ: ' + Object.keys(state.labPassed || {}).length);
    const list = add(content, 'ul');
    for (const node of nodes) {
      const item = add(list, 'li');
      button(item, node.title, () => openNode(node.id));
      if (state.done.includes(node.id)) add(item, 'small', ' · Пройдено');
    }
  }
  if (view === 'exam') renderExam();
  if(view==='cards')for(const c of cards){
    const box=add(content,'section','','box');add(box,'strong',c.front);
    add(details(box,'Показать ответ'),'p',c.back);
    for(const choice of ['Знаю','Повторить']){
      const b=button(box,choice,()=>{state.cards[c.id]=choice;save();render();});
      b.setAttribute('aria-pressed',state.cards[c.id]===choice);
      if(state.cards[c.id]===choice)b.className='primary';
    }
  }
  if(view==='terms')for(const t of glossary){
    add(content,'h3',t.term);add(content,'small',t.en);add(content,'p',t.definition);source(content,t.page);
    button(content,'К шагу',()=>openNode(t.node_id));
  }
  if(view==='summary'){
    button(content,'Печать / PDF',()=>window.print());
    for(const n of nodes){add(content,'h3',n.title);paragraphs(content,n.summary,n);dataMeaning(content,n);}
  }
  if(view==='map')drawGraph();
  if(view==='map')for(const n of nodes){
    const box=add(content,'section','','box');button(box,n.title,()=>openNode(n.id),'primary');
    const types={prerequisite:'Предпосылка',example:'Пример',refutes_misconception:'Исправляет заблуждение',to_data:'Переход к данным'};
    for(const l of n.links || []){
      const target=nodes.find(x=>x.id===l.to);if(!target)continue;
      const row=add(box,'p',types[l.type]+' → ');button(row,target.title,()=>openNode(target.id));
    }
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

function renderExam() {
  const form = add(content, 'form');
  const checks = tasks.map(task => quiz(form, task, true)).filter(Boolean);
  if (!checks.length) {
    add(form, 'p', 'В этой главе пока нет заданий для экзамена.');
    return;
  }
  const submit = add(form, 'button', 'Завершить экзамен', 'primary');
  submit.type = 'submit';
  const result = add(form, 'output', '', 'examResult');
  result.setAttribute('aria-live', 'polite');
  form.onsubmit = event => {
    event.preventDefault();
    const score = checks.filter(check => check()).length;
    result.textContent = 'Верных ответов: ' + score + ' из ' + checks.length + '.';
    for (const control of form.querySelectorAll('input, button')) control.disabled = true;
    button(form, 'Начать заново', render);
  };
}

function drawGraph(){
  const ns='http://www.w3.org/2000/svg';
  const svg=document.createElementNS(ns,'svg');
  svg.setAttribute('viewBox','0 0 360 '+(nodes.length*54+20));
  svg.setAttribute('role','img');
  svg.setAttribute('aria-label','Связи учебных шагов. Доступные переходы перечислены ниже.');
  function shape(tag,attrs){
    const e=document.createElementNS(ns,tag);
    Object.entries(attrs).forEach(([k,v])=>e.setAttribute(k,v));
    svg.append(e);return e;
  }
  nodes.forEach((n,i)=>(n.links || []).forEach(l=>{
    const j=nodes.findIndex(x=>x.id===l.to);if(j<0)return;
    const y=27+i*54, end=27+j*54, bend=14+Math.min(30,Math.abs(i-j)*8);
    shape('path',{d:'M 60 '+y+' C '+bend+' '+y+', '+bend+' '+end+', 60 '+end,fill:'none',stroke:'var(--accent)','stroke-width':2});
  }));
  nodes.forEach((n,i)=>{
    const y=27+i*54;
    shape('circle',{cx:60,cy:y,r:12,fill:'var(--soft)',stroke:'var(--muted)'});
    shape('text',{x:60,y:y+4,'text-anchor':'middle',fill:'var(--ink)','font-size':11}).textContent=n.order;
    shape('text',{x:80,y:y+5,fill:'var(--ink)','font-size':12}).textContent=n.title.length>35?n.title.slice(0,34)+'…':n.title;
  });
  content.append(svg);
}

function render(){
  $('route').replaceChildren();
  for(const part of layer.parts){
    add($('route'),'div',part.title,'part');
    for(const n of nodes.filter(n=>n.part_id===part.id)){
      const b=button($('route'),(state.done.includes(n.id)?'✓ ':n.order+'. ')+n.title,()=>openNode(n.id),'routeBtn');
      if(n===current)b.setAttribute('aria-current','step');
    }
  }
  $('progress').hidden = $('progressLabel').hidden = !nodes.length;
  $('progress').max=nodes.length || 1;$('progress').value=state.done.length;
  $('progressLabel').textContent='Пройдено '+state.done.length+' из '+nodes.length;
  $('toolbar').replaceChildren();
  const toolbarGroup = add($('toolbar'), 'div', '', 'toolbarGroup');
  add(toolbarGroup, 'strong', views[view]);
  if (view !== 'lesson') button(toolbarGroup, 'К уроку', () => openView('lesson'));
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
    ? 'Загруженные материалы доступны в чате и лаборатории.'
    : 'Добавьте источник, чтобы начать практику.', 'muted');
  for (const [id, icon] of activities.filter(([id]) => nodes.length || ['lab', 'progress'].includes(id))) {
    const control = button($('tools'), '', () => openView(id), 'toolBtn');
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
$('search').onsubmit=e=>{
  e.preventDefault();const query=normalize($('query').value);const results=$('results');results.replaceChildren();
  if(!query)return;
  for(const n of nodes){
    const hits=(n.claims || []).filter(c=>normalize(c.text+' '+c.quote).includes(query));
    if(!hits.length && !normalize(n.title).includes(query))continue;
    button(results,n.title,()=>openNode(n.id));
    hits.slice(0,3).forEach(c=>evidence(details(results,'Фрагмент · стр. '+c.page,'evidence'),c));
  }
  if(!results.childElementCount)add(results,'p','Совпадений в материалах главы нет.');
};
document.title=$('title').textContent=chapter.title_short || chapter.title;
$('author').textContent=[chapter.author, chapter.year].filter(Boolean).join(' · ');
$('meta').textContent=spaceId ? 'Учебное пространство' : nodes.length+' '+({one:'шаг',few:'шага',many:'шагов'}[new Intl.PluralRules('ru').select(nodes.length)])+(nodes.every(n=>n.minutes) ? ' / '+nodes.reduce((total,n)=>total+n.minutes,0)+' мин' : '');
