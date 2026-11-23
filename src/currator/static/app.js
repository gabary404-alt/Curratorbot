const $ = id => document.getElementById(id);
const conversation = $('conversation');
const prompt = $('prompt');
const hint = $('hint');
const record = $('record');
const language = $('lang');
const sessionId = Array.from(crypto.getRandomValues(new Uint8Array(12)),
  byte => byte.toString(16).padStart(2, '0')).join('');
const modes = {
  mock: ['Offline demonstration', 'Prepared text replies. Audio is disabled.'],
  rehearsal: ['Voice rehearsal', 'Prepared replies with live speech features.'],
  live: ['Live AI', ''],
};
let config = null;
let phase = 'idle';
let recording = null;
let speech = null;
const history = [];

function bubble(text, kind = 'bot', lang) {
  const entry = document.createElement('div');
  entry.className = 'bubble ' + kind;
  entry.textContent = text;
  if (lang) entry.lang = lang;
  conversation.appendChild(entry);
  conversation.scrollTop = conversation.scrollHeight;
  return entry;
}

function setPhase(next, message) {
  phase = next;
  const idle = phase === 'idle';
  const active = phase === 'recording';
  $('send').disabled = !config || !idle;
  language.disabled = !idle;
  $('retrieval').disabled = !idle || !config || config.mode === 'mock';
  record.disabled = !active && (
    !idle || !config?.speech_input.includes(language.value) ||
    !navigator.mediaDevices?.getUserMedia || !window.MediaRecorder
  );
  record.setAttribute('aria-pressed', String(active));
  record.setAttribute('aria-label', active ? 'Stop recording and send' : 'Record spoken question');
  record.classList.toggle('recording', active);
  if (message) hint.textContent = message;
}

function readyMessage() {
  if (!config) return 'Waiting for the server…';
  if (config.mode === 'mock') return 'Type a question to try the offline demonstration.';
  if (!config.speech_input.includes(language.value)) return 'Type an English question during rehearsal.';
  if (record.disabled) return 'Microphone unavailable. Use localhost or HTTPS, or type a question.';
  return 'Tap the microphone to record. Tap again to send.';
}

async function api(path, options = {}) {
  const response = await fetch(path, options);
  const data = await response.json();
  if (!response.ok) {
    const message = typeof data.detail === 'string' ? data.detail : 'Check your input and try again.';
    throw new Error(message);
  }
  return data;
}

function post(path, body, signal) {
  return api(path, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body),
    signal,
  });
}

async function loadStatus() {
  try {
    config = await api('/api/status');
    if (!config.speech_input.includes('auto') && language.value === 'auto') language.value = 'rw';
    const [title, notice] = modes[config.mode];
    $('status').textContent = title;
    $('mode-warning').textContent = [notice, config.hosted ? 'Browser demo. Robot controls run on the robot computer.' : ''].filter(Boolean).join(' ');
    setPhase('idle');
    hint.textContent = readyMessage();
  } catch {
    $('status').textContent = 'Disconnected';
    hint.textContent = 'Start the server and refresh this page.';
  }
}

function stopSpeech() {
  const previous = speech;
  speech = null;
  previous?.controller.abort();
  previous?.player?.pause();
  if ('speechSynthesis' in window) window.speechSynthesis.cancel();
  $('face').classList.remove('talking');
  $('stop-audio').disabled = true;
}

$('stop-audio').addEventListener('click', () => {
  stopSpeech();
  if (phase === 'idle') hint.textContent = 'Speech stopped.';
});

function appendPlayButton(entry, label, play) {
  entry.querySelector('button')?.remove();
  const button = document.createElement('button');
  button.type = 'button';
  button.textContent = label;
  button.className = 'replay';
  button.addEventListener('click', () => {
    if (phase !== 'idle') return;
    button.remove();
    play();
  });
  entry.append(button);
}

async function speak(text, lang, entry, audioUrl = null) {
  stopSpeech();
  if (!config.speech_output.includes(lang)) return;
  const active = {controller: new AbortController(), player: null};
  speech = active;
  $('stop-audio').disabled = false;
  const finish = (message) => {
    if (speech !== active) return;
    stopSpeech();
    if (phase === 'idle') hint.textContent = message || readyMessage();
  };
  const started = () => {
    if (speech === active) {
      $('face').classList.add('talking');
      hint.textContent = 'Speaking…';
    }
  };

  try {
    if (!audioUrl && (lang !== 'en' || config.mode === 'live')) {
      hint.textContent = 'Preparing voice…';
      const data = await post('/api/speech/synthesize', {
        text: Array.from(text).slice(0, 800).join(''),
        language: lang,
      }, active.controller.signal);
      if (speech !== active) return;
      audioUrl = data.audio_url;
    }
    if (!audioUrl && lang === 'en') {
      if (!('speechSynthesis' in window)) throw new Error('English speech unavailable on this device.');
      const voices = window.speechSynthesis.getVoices().filter(item => item.lang.startsWith('en'));
      const voice = voices.find(item => /natural|neural|premium/i.test(item.name)) || voices[0];
      const utterance = new SpeechSynthesisUtterance(text);
      utterance.lang = 'en-US';
      utterance.rate = .98;
      if (voice) utterance.voice = voice;
      utterance.onstart = started;
      utterance.onend = () => finish();
      utterance.onerror = () => {
        if (speech !== active) return;
        appendPlayButton(entry, 'Try speech again', () => void speak(text, lang, entry));
        finish('English speech unavailable. Check the installed English voice.');
      };
      window.speechSynthesis.speak(utterance);
      return;
    }
    active.player = new Audio(audioUrl);
    active.player.onplaying = started;
    active.player.onended = () => finish();
    active.player.onerror = () => {
      if (speech !== active) return;
      appendPlayButton(entry, 'Try speech again', () => void speak(text, lang, entry));
      finish('The reply audio could not play.');
    };
    await active.player.play();
  } catch (error) {
    if (speech !== active) return;
    if (error.name === 'NotAllowedError' && active.player) {
      appendPlayButton(entry, 'Play reply', () => {
        void speak(text, lang, entry, audioUrl);
      });
      finish('Tap Play reply to hear the answer.');
      return;
    }
    appendPlayButton(entry, 'Try speech again', () => void speak(text, lang, entry));
    finish(error.message);
  }
}

function appendSources(sources) {
  if (!sources?.length) return;
  const links = document.createElement('div');
  links.className = 'sources';
  for (const source of sources) {
    if (!source.url?.startsWith('https://')) continue;
    const link = document.createElement('a');
    link.href = source.url;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    link.textContent = source.label;
    links.appendChild(link);
  }
  conversation.appendChild(links);
  conversation.scrollTop = conversation.scrollHeight;
}

async function ask(text, lang) {
  stopSpeech();
  bubble(text, 'user', lang === 'auto' ? undefined : lang);
  setPhase('thinking', 'Thinking…');
  try {
    const result = await post('/api/chat', {
      text, language: lang, session_id: sessionId, retrieval: $('retrieval').value, history,
    });
    if (config.mode === 'live' && !['live_unavailable', 'source_unavailable'].includes(result.source_mode)) {
      history.push({role: 'user', text}, {role: 'model', text: result.reply.slice(0, 1500)});
      if (history.length > 6) history.splice(0, 2);
    }
    const replyLang = result.language || lang;
    const response = bubble(result.reply, 'bot', replyLang);
    if (result.simulated) {
      const notice = document.createElement('small');
      notice.textContent = config.mode === 'rehearsal' ? 'Prepared rehearsal reply' : 'Simulated reply';
      response.append(notice);
    }
    appendSources(result.sources);
    $('mood').textContent = result.reply.slice(0, 90);
    $('mood').lang = replyLang;
    setPhase('idle');
    hint.textContent = result.source_mode === 'live_unavailable' ?
      'Current information could not be verified.' : readyMessage();
    void speak(result.reply, replyLang, response);
  } catch (error) {
    bubble('Could not answer. ' + error.message);
    setPhase('idle', 'Please try again.');
  }
}

$('chat-form').addEventListener('submit', event => {
  event.preventDefault();
  const text = prompt.value.trim();
  if (!config || phase !== 'idle' || !text) return;
  prompt.value = '';
  void ask(text, language.value);
});

language.addEventListener('change', () => {
  stopSpeech();
  setPhase('idle');
  hint.textContent = readyMessage();
});

function closeRecording(capture) {
  clearTimeout(capture.timer);
  capture.stream.getTracks().forEach(track => track.stop());
  if (recording === capture) recording = null;
}

async function transcribe(capture) {
  closeRecording(capture);
  const blob = new Blob(capture.chunks, {type: capture.recorder.mimeType});
  if (!blob.size) {
    setPhase('idle', 'No audio captured. Try recording again.');
    return;
  }
  const form = new FormData();
  const suffix = blob.type.includes('mp4') ? 'mp4' : blob.type.includes('ogg') ? 'ogg' : 'webm';
  form.append('audio', blob, 'question.' + suffix);
  setPhase('transcribing', 'Transcribing…');
  try {
    const result = await api('/api/speech/transcribe?language=' + capture.lang, {
      method: 'POST', body: form,
    });
    if (result.needs_confirmation) {
      prompt.value = result.text;
      setPhase('idle', 'Uzuza cyangwa ukosore amagambo numvise, hanyuma wohereze. / Review the transcript before sending.');
      prompt.focus();
      return;
    }
    await ask(result.text, capture.lang);
  } catch (error) {
    bubble('Speech recognition: ' + error.message);
    setPhase('idle', 'Try the microphone again or type a question.');
  }
}

record.addEventListener('click', async () => {
  if (phase === 'recording' && recording?.recorder.state === 'recording') {
    setPhase('transcribing', 'Finishing recording…');
    recording.recorder.stop();
    return;
  }
  if (!config || phase !== 'idle' || record.disabled) return;
  const lang = language.value;
  setPhase('opening', 'Opening microphone…');
  stopSpeech();
  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({
      audio: {echoCancellation: true, noiseSuppression: true, channelCount: 1},
    });
    const formats = ['audio/webm;codecs=opus', 'audio/mp4', 'audio/ogg;codecs=opus'];
    const mimeType = formats.find(type => MediaRecorder.isTypeSupported(type));
    const recorder = new MediaRecorder(stream, mimeType ? {mimeType} : undefined);
    const capture = {recorder, stream, lang, chunks: [], timer: null};
    recording = capture;
    recorder.ondataavailable = event => {
      if (event.data.size) capture.chunks.push(event.data);
    };
    recorder.onstop = () => {
      if (recording === capture) void transcribe(capture);
    };
    recorder.onerror = () => {
      closeRecording(capture);
      setPhase('idle', 'Recording failed. Try the microphone again.');
    };
    recorder.start();
    setPhase('recording', 'Recording… Tap again to send, or wait 15 seconds.');
    capture.timer = setTimeout(() => {
      if (recorder.state === 'recording') recorder.stop();
    }, 15000);
  } catch (error) {
    if (recording && recording.stream === stream) closeRecording(recording);
    else stream?.getTracks().forEach(track => track.stop());
    setPhase('idle', error.name === 'NotAllowedError' ?
      'Microphone permission was denied. Enable it for this page or type a question.' :
      'Microphone unavailable. Check the device or type a question.');
  }
});

setPhase('idle');
void loadStatus();
