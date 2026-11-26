'use strict';

let practiceSet;
let examSet;
let examAttempt;
const examThreshold = 70;
const examRunning = () => Boolean(state.exam);

function generationControl(parent, mode, onReady) {
  const status = add(parent, 'p', '', 'assessmentStatus');
  status.setAttribute('role', 'status');
  const control = button(parent, mode === 'exam' ? 'Сгенерировать вариант с ИИ' : 'Сгенерировать тест с ИИ', async () => {
    const sources = serverSources();
    if (!sources.length) { status.textContent = 'Отметь источники в левой панели.'; return; }
    control.disabled = true;
    status.textContent = 'ИИ составляет вопросы по выбранным источникам…';
    try {
      onReady(await api('assessments', {mode, sources}));
      if (view === mode) render();
    } catch (error) { status.textContent = error.message; }
    finally { control.disabled = false; }
  });
  if (!service || service.mock) {
    control.disabled = true;
    status.textContent = service?.mock
      ? 'Тестовый режим сервера. Для новых вопросов нужен профиль ИИ.'
      : 'Для генерации вопросов подключи сервер QABAT.';
  }
}

function renderPractice() {
  generationControl(content, 'practice', result => { practiceSet = result; });
  if (practiceSet) add(content, 'p', 'Вопросы сгенерированы моделью ' + practiceSet.model, 'muted');
  const questions = practiceSet?.tasks || tasks;
  if (!questions.length) add(content, 'p', 'Добавь источник и сгенерируй тест по его материалу.');
  for (const task of questions) quiz(content, task);
}

function chapterExamTasks() {
  const bank = tasks.filter(task => ['single', 'multi', 'order', 'cloze', 'calc'].includes(task.type));
  const firstByStep = new Map();
  for (const task of bank) {
    if (!firstByStep.has(task.node_id)) firstByStep.set(task.node_id, task);
  }
  const ranked = [...firstByStep.values()];
  if (ranked.length <= 10) return [...ranked, ...bank.filter(t => firstByStep.get(t.node_id) !== t)].slice(0, 10);
  return Array.from({length: 10}, (_, i) => ranked[Math.round(i * (ranked.length - 1) / 9)]);
}

function renderExam() {
  if (examAttempt) { content.append(examAttempt); return; }
  if (state.exam) {
    examAttempt = buildExamAttempt(state.exam);
    content.append(examAttempt);
    return;
  }
  const questions = examSet?.tasks || chapterExamTasks();
  if (!questions.length) {
    add(content, 'p', 'Добавь источники и сгенерируй экзамен по их материалам.');
    generationControl(content, 'exam', result => { examSet = result; });
    return;
  }
  const minutes = Math.max(5, questions.length * 2);
  const cover = add(content, 'section', '', 'examPolicy');
  add(cover, 'h3', 'Правила экзамена');
  const facts = add(cover, 'div', '', 'examFacts');
  for (const [label, value] of [['Вопросы', questions.length], ['Время', minutes + ' мин'], ['Проходной балл', examThreshold + '%']]) {
    const cell = add(facts, 'div');
    add(cell, 'strong', String(value));
    add(cell, 'small', label);
  }
  const rules = add(cover, 'ul');
  for (const rule of [
    'Выполняй работу самостоятельно. Во время попытки нельзя пользоваться чатом, конспектом и внешними подсказками.',
    'За верный ответ начисляется 1 балл. Пропуск или неверный ответ дают 0 баллов.',
    'Менять ответы можно до сдачи. По истечении времени работа сдаётся автоматически.',
    'Итог и разбор ответов появятся после сдачи.'
  ]) add(rules, 'li', rule);
  const previous = state.lastExam;
  if (previous) add(cover, 'p', 'Предыдущая попытка: ' + previous.score + ' из ' + previous.total + '.', 'muted');
  add(cover, 'p', examSet ? 'Вариант сгенерирован моделью ' + examSet.model + '.'
    : 'Вариант собран из банка заданий главы.', 'muted');
  const consent = add(cover, 'label', '', 'choice');
  const check = add(consent, 'input');
  check.type = 'checkbox';
  consent.append(' Я прочитал правила и готов начать.');
  const start = button(cover, 'Начать экзамен', () => {
    state.exam = {questions, deadline: Date.now() + minutes * 60000, index: 0, answers: []};
    save();
    examAttempt = buildExamAttempt(state.exam);
    render();
    examAttempt.querySelector('h3').focus();
  }, 'primary');
  start.disabled = true;
  check.onchange = () => { start.disabled = !check.checked; };
  generationControl(cover, 'exam', result => { examSet = result; });
}

function buildExamAttempt(attempt) {
  const {questions, deadline} = attempt;
  const area = document.createElement('section');
  area.className = 'examAttempt';
  area.dataset.running = 'true';
  const bar = add(area, 'div', '', 'examBar');
  const heading = add(bar, 'h3');
  heading.tabIndex = -1;
  const clock = add(bar, 'span', '', 'examClock');
  clock.setAttribute('role', 'timer');
  const shortcuts = add(area, 'nav', '', 'examNumbers');
  shortcuts.setAttribute('aria-label', 'Номера вопросов');
  const questionArea = add(area, 'div');
  const controls = add(area, 'div', '', 'examControls');
  const result = add(area, 'div');
  result.setAttribute('aria-live', 'polite');
  let index = 0, finished = false;
  const items = questions.map((task, i) => {
    const card = add(questionArea, 'section');
    const response = quiz(card, task, true);
    if (attempt.answers[i] != null) response.restore(attempt.answers[i]);
    return {task, card, ...response};
  });
  const tabs = questions.map((_, i) => button(shortcuts, String(i + 1), () => show(i, true)));
  const prev = button(controls, 'Предыдущий', () => show(index - 1, true));
  const next = button(controls, 'Следующий', () => show(index + 1, true));
  button(controls, 'Сдать экзамен', async () => {
    if (Date.now() >= deadline) { finish(true); return; }
    const blank = items.filter(item => !item.answered()).length;
    const choice = await spaceDialog('Сдать экзамен?',
      blank ? 'Без ответа: ' + blank + '. Они будут оценены в 0 баллов.' : 'После сдачи изменить ответы уже нельзя.',
      [['submit', 'Сдать экзамен']]);
    if (choice) finish(Date.now() >= deadline);
  }, 'primary');

  function markAnswers() {
    tabs.forEach((tab, i) => {
      tab.dataset.answered = String(items[i].answered());
      tab.setAttribute('aria-label', 'Вопрос ' + (i + 1) + (items[i].answered() ? ', есть ответ' : ', без ответа'));
    });
  }
  function show(i, focus = false) {
    index = i;
    heading.textContent = 'Вопрос ' + (i + 1) + ' из ' + items.length;
    items.forEach((item, n) => { item.card.hidden = n !== i; });
    tabs.forEach((tab, n) => tab.setAttribute('aria-current', n === i ? 'step' : 'false'));
    prev.disabled = i === 0;
    next.disabled = i === items.length - 1;
    markAnswers();
    if (focus) {
      attempt.index = index;
      save();
      heading.focus();
    }
  }
  function finish(expired) {
    if (finished) return;
    finished = true;
    area.dataset.running = 'false';
    clearInterval(timer);
    items.forEach((item, i) => item.restore(attempt.answers[i] ?? []));
    const score = items.filter(item => item.answered() && item.check()).length;
    const percent = Math.round(score / items.length * 100);
    const passed = score * 100 >= examThreshold * items.length;
    delete state.exam;
    state.lastExam = {score, total: items.length};
    save();
    questionArea.hidden = shortcuts.hidden = controls.hidden = clock.hidden = true;
    heading.textContent = expired ? 'Время вышло' : 'Экзамен завершён';
    add(result, 'h3', passed ? 'Экзамен пройден' : 'Проходной балл не набран');
    add(result, 'p', score + ' из ' + items.length + ' · ' + percent + '%');
    const review = details(result, 'Разбор ответов');
    items.forEach((item, i) => {
      const entry = add(review, 'div', '', 'box');
      add(entry, 'strong', (i + 1) + '. ' + (!item.answered() ? 'Пропущено' : item.check() ? 'Верно' : 'Неверно'));
      rich(add(entry, 'p'), item.task.question);
      bookText(entry, 'p', 'Правильный ответ · ' + item.answer);
      if (item.task.explanation) bookText(entry, 'p', item.task.explanation);
      if (item.task.citation) {
        const citation = item.task.citation;
        bookText(details(entry, citation.source + ' · стр. ' + citation.page), 'blockquote', citation.quote);
      }
    });
    button(result, 'Новая попытка', () => { examAttempt = null; render(); });
    if (area.isConnected) { render(); heading.focus(); }
  }
  function tick() {
    const remaining = Math.ceil((deadline - Date.now()) / 1000);
    if (remaining <= 0) { finish(true); return; }
    clock.textContent = Math.floor(remaining / 60) + ':' + String(remaining % 60).padStart(2, '0');
  }
  questionArea.addEventListener('input', () => {
    if (Date.now() >= deadline) { finish(true); return; }
    attempt.answers[index] = items[index].snapshot();
    save();
    markAnswers();
  });
  const timer = setInterval(tick, 500);
  show(Math.min(items.length - 1, attempt.index));
  if (Date.now() < deadline) tick();
  return area;
}
