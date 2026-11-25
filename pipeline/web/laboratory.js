'use strict';

function labPost(method, body) {
  return api('lab/' + method, body, 22000);
}

let preferredSource;
function labSource() {
  const ids = serverSources();
  return ids.includes(preferredSource) ? preferredSource : ids.at(-1);
}

function labLink(parent, label, url) {
  const link = add(parent, 'a', label);
  Object.assign(link, {href: url, target: '_blank', rel: 'noopener'});
}

function textExercise(parent, node, instruction) {
  add(parent, 'p', instruction);
  const claim = node.claims?.find(c => c.verified && c.quote);
  if (!claim) {
    button(parent, 'Открыть материал урока', () => openView('lesson'));
    return;
  }
  const label = add(parent, 'label', 'Сформулируй вывод своими словами');
  add(label, 'textarea').rows = 2;
  evidence(details(parent, 'Сверить с цитатой автора'), claim);
}

async function specimenLab(parent) {
  const sources = details(parent, 'Внешние учебные коллекции');
  for (const [name, url] of [
    ['Virtual Microscope · коллекции шлифов', 'https://www.virtualmicroscope.org/'],
    ['eRocK · обнажения и образцы', 'https://www.e-rock.co.uk/'],
    ['Visible Geology · геологические структуры', 'https://www.visiblegeology.com/']
  ]) labLink(add(sources, 'p'), name + ' ↗', url);
  const node = current;
  if (!service?.laboratory) {
    textExercise(parent, node, 'Для проверки по фотографии нужен сервер тьютора. В автономном курсе можно поработать с цитатой.');
    return;
  }
  const sourceId = labSource();
  if (!sourceId) { add(parent, 'p', 'Выбери источник в левой панели.'); return; }
  const label = add(parent, 'label', 'Материал для практики ');
  const picker = add(label, 'select');
  for (const id of serverSources()) add(picker, 'option', sourceNames.get(id)).value = id;
  picker.value = sourceId;
  picker.onchange = () => { preferredSource = picker.value; render(); };
  const status = add(parent, 'p', 'Подбираем задание по уроку…');
  status.setAttribute('role', 'status');
  let task;
  try {
    task = await labPost('open', {source: sourceId, node: node.id, review: state.done.includes(node.id)});
  } catch (error) {
    status.textContent = 'Не удалось открыть задание. ' + error.message;
    button(parent, 'Повторить', () => { parent.replaceChildren(); specimenLab(parent); });
    textExercise(parent, node, 'Пока можно поработать с текстом урока.');
    return;
  }
  if (!parent.isConnected) return;
  status.remove();
  if (task.action === 'study_text') {
    if (sourceId === chapter.id) textExercise(parent, node, task.instructions);
    else {
      add(parent, 'p', task.instructions);
      add(add(parent, 'label', 'Твой вывод'), 'textarea');
      if (task.evidence) add(details(parent, 'Сверить с источником · стр. ' + task.evidence.page), 'blockquote', task.evidence.quote);
    }
    return;
  }
  if (task.action !== 'open_virtual_lab' || !['rock_identification', 'mineral_identification'].includes(task.activity)) {
    textExercise(parent, node, 'Формат задания недоступен. Найди в тексте основание для вывода.');
    return;
  }
  add(parent, 'small', task.guidance + ' · ' + (task.activity === 'mineral_identification' ? 'Определение минерала' : 'Определение породы'), 'kicker');
  add(parent, 'p', task.instructions);
  const body = {source: sourceId, node: node.id, asset_id: task.asset_id};
  const form = document.createElement('form');
  specimenViewer(parent, task, () => {
    form.hidden = true;
    textExercise(parent, node, 'Фото недоступно. Оригинал можно открыть по ссылке выше или продолжить по тексту.');
  });
  parent.append(form);
  const choice = add(add(form, 'label', 'Как бы ты определил этот образец?'), 'select');
  add(choice, 'option', 'Выбери гипотезу').value = '';
  choice.required = true;
  for (const option of task.options) add(choice, 'option', option);
  const observation = add(add(form, 'label', task.question), 'textarea');
  Object.assign(observation, {required: true, maxLength: 1200, rows: 3});
  const tutor = details(form, 'Подсказка тьютора');
  add(tutor, 'p', task.hint);
  const query = add(add(tutor, 'label', 'Вопрос по образцу'), 'input');
  query.maxLength = 400;
  const hint = add(tutor, 'p');
  hint.setAttribute('role', 'status');
  const ask = button(tutor, 'Спросить', async () => {
    if (!query.value.trim()) { query.focus(); return; }
    ask.disabled = true;
    hint.textContent = 'Готовим подсказку…';
    try {
      const reply = await labPost('hint', {...body, question: query.value.trim()});
      hint.textContent = reply.by + ' · ' + reply.hint;
    } catch { hint.textContent = 'Тьютор недоступен. Попробуй ещё раз.'; }
    finally { ask.disabled = false; }
  });
  const submit = add(form, 'button', 'Проверить ответ', 'primary');
  const feedback = add(form, 'p');
  feedback.setAttribute('role', 'status');
  const progressKey = sourceId + '/' + node.id + '/' + task.asset_id;
  if (state.labPassed?.[progressKey]) feedback.textContent = 'Работа уже зачтена. Можно потренироваться ещё раз.';
  form.onsubmit = async event => {
    event.preventDefault();
    submit.disabled = true;
    feedback.textContent = 'Проверяем наблюдение…';
    try {
      const result = await labPost('grade', {...body, choice: choice.value, observation: observation.value.trim()});
      const labels = {correct: 'Зачтено. ', retry: 'Попробуй ещё раз. ', uncertain: 'Требует уточнения. '};
      feedback.textContent = labels[result.status] + result.feedback + (result.followup ? ' ' + result.followup : '');
      if (result.status === 'correct') {
        state.labPassed ||= {};
        state.labPassed[progressKey] = true;
        if (!save()) feedback.textContent += ' Результат доступен до закрытия вкладки.';
      }
    } catch { feedback.textContent = 'Проверка недоступна. Ответ сохранён в поле, можно повторить.'; }
    finally { submit.disabled = false; }
  };
}
