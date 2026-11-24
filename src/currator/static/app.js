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
let lastSpeechLanguage = null;
const END_OF_TURN_MS = 900;
const AUDIO_CHECK_MS = 50;

function bubble(text, kind = 'bot', lang) {
  const entry = document.createElement('div');
  entry.className = 'bubble ' + kind;
  entry.textContent = text;
  if (lang) entry.lang = lang;
  conversation.appendChild(entry);
  conversation.scrollTop = conversation.scrollHeight;
  return entry;
}

const activityLabels = {
  opening: 'Opening microphone…',
  recording: 'Listening…',
  transcribing: 'Understanding your speech…',
  thinking: 'Thinking…',
  researching: 'Checking sources…',
  preparing: 'Preparing my voice…',
  speaking: 'Speaking…',
};

function setFace(state) {
  $('face').setAttribute('data-state', state);
  $('activity').textContent = activityLabels[state] || '';
}

function setPhase(next, message) {
  setFace(next);
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
  return 'Tap the microphone, speak, then pause for a reply.';
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
  setFace(phase);
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

async function speak(text, lang, entry, audioUrl = null, remainder = '') {
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
      setFace('speaking');
      hint.textContent = 'Speaking…';
    }
  };

  try {
    const generate = async part => (await post('/api/speech/synthesize', {
      text: part, language: lang,
    }, active.controller.signal)).audio_url;
    const nextPart = () => {
      const chars = Array.from(remainder);
      let end = Math.min(800, chars.length);
      if (end < chars.length) {
        for (let i = end - 1; i > 0; i--) {
          if (/\s/.test(chars[i])) { end = i; break; }
        }
      }
      const part = chars.slice(0, end).join('');
      remainder = chars.slice(end).join('').trimStart();
      return part;
    };
    if (!audioUrl) {
      setFace('preparing');
      hint.textContent = 'Preparing my voice…';
      remainder = text;
      audioUrl = await generate(nextPart());
      if (speech !== active) return;
    }
    while (speech === active) {
      if (!audioUrl) throw new Error('Nshuti’s voice is temporarily unavailable.');
      active.player = new Audio(audioUrl);
      active.player.onplaying = started;
      active.player.onerror = () => {
        if (speech !== active) return;
        appendPlayButton(entry, 'Try speech again', () => void speak(text, lang, entry));
        finish('The reply audio could not play.');
      };
      await active.player.play();
      if (speech !== active) return;
      if (!remainder) { active.player.onended = () => finish(); return; }
      const ended = new Promise(resolve => {
        active.player.onended = resolve;
        active.controller.signal.addEventListener('abort', resolve, {once: true});
      });
      const next = generate(nextPart()).catch(() => null);
      await ended;
      if (speech !== active) return;
      audioUrl = await next;
    }
  } catch (error) {
    if (speech !== active) return;
    if (error.name === 'NotAllowedError' && active.player) {
      appendPlayButton(entry, 'Play reply', () => {
        void speak(text, lang, entry, audioUrl, remainder);
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

async function requestReply(body, onProgress) {
  const response = await fetch('/api/chat', {
    method: 'POST',
    headers: {'Content-Type': 'application/json', Accept: 'application/x-ndjson'},
    body: JSON.stringify(body),
  });
  if (!response.ok || !response.headers?.get('content-type')?.includes('application/x-ndjson')) {
    const result = await response.json();
    if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : 'Check your input and try again.');
    return result;
  }
  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
  let pending = '';
  try {
    while (true) {
      const {done, value} = await reader.read();
      if (done) break;
      pending += value;
      let newline;
      while ((newline = pending.indexOf('\n')) !== -1) {
        const event = JSON.parse(pending.slice(0, newline));
        pending = pending.slice(newline + 1);
        if (event.error) throw new Error(event.error);
        if (event.reply) return event.reply;
        if (['thinking', 'researching', 'preparing'].includes(event.phase)) {
          onProgress(event.phase);
        }
      }
    }
    throw new Error('The reply was interrupted. Please try again.');
  } finally {
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}

async function ask(text, lang) {
  stopSpeech();
  bubble(text, 'user', lang === 'auto' ? undefined : lang);
  const progress = document.createElement('div');
  progress.className = 'message-progress';
  progress.setAttribute('aria-hidden', 'true');
  conversation.appendChild(progress);
  const updateProgress = state => {
    setPhase(state, activityLabels[state]);
    progress.textContent = {
      researching: 'Checking sources…',
      preparing: 'Getting your spoken reply ready…',
      thinking: 'Generating a reply…',
    }[state];
    conversation.scrollTop = conversation.scrollHeight;
  };
  updateProgress('thinking');
  const timer = setTimeout(() => {
    progress.textContent = 'Still working on your reply…';
  }, 10000);
  try {
    const result = await requestReply({
      text, language: lang, session_id: sessionId, retrieval: $('retrieval').value, history,
      include_audio: config.speech_output.length > 0, segmented_audio: true,
    }, updateProgress);
    progress.remove();
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
    if (result.audio_error) {
      hint.textContent = result.audio_error;
      appendPlayButton(response, 'Play reply', () => void speak(result.reply, replyLang, response));
    } else if (result.audio_url) {
      void speak(result.reply, replyLang, response, result.audio_url, result.remaining_speech);
    } else if (result.audio_url === undefined) {
      // Compatible with earlier servers during a rolling deployment.
      void speak(result.reply, replyLang, response);
    }
  } catch (error) {
    progress.remove();
    bubble('Could not answer. ' + error.message);
    setPhase('idle', 'Please try again.');
  } finally {
    clearTimeout(timer);
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
  capture.stopMonitoring?.();
  capture.stream.getTracks().forEach(track => track.stop());
  if (recording === capture) recording = null;
}

function finishTurn(capture) {
  if (recording !== capture || capture.recorder.state !== 'recording') return;
  setPhase('transcribing', 'Finishing recording…');
  capture.stopMonitoring?.();
  capture.recorder.stop();
}

function watchForPause(capture) {
  const AudioContext = window.AudioContext || window.webkitAudioContext;
  if (!AudioContext) return false;

  let context;
  try {
    context = new AudioContext();
    const source = context.createMediaStreamSource(capture.stream);
    const analyser = context.createAnalyser();
    analyser.fftSize = 1024;
    source.connect(analyser);
    const samples = new Float32Array(analyser.fftSize);
    const started = performance.now();
    let floor = 0.004;
    let voicedMs = 0;
    let lastVoice = started;
    let heardVoice = false;
    const timer = setInterval(() => {
      if (context.state !== 'running') return;
      analyser.getFloatTimeDomainData(samples);
      const rms = Math.sqrt(samples.reduce((energy, value) => energy + value * value, 0) / samples.length);
      const now = performance.now();
      const threshold = Math.max(0.012, floor * 2.5);
      if (rms >= threshold) {
        voicedMs += AUDIO_CHECK_MS;
        lastVoice = now;
        heardVoice ||= voicedMs >= 200;
      } else if (!heardVoice) {
        floor = Math.max(0.002, floor * 0.9 + rms * 0.1);
        voicedMs = 0;
      } else if (now - lastVoice >= END_OF_TURN_MS) {
        finishTurn(capture);
      }
    }, AUDIO_CHECK_MS);
    capture.stopMonitoring = () => {
      capture.stopMonitoring = null;
      clearInterval(timer);
      source.disconnect();
      void context.close().catch(() => {});
    };
    void context.resume().catch(() => capture.stopMonitoring?.());
    return true;
  } catch {
    if (context) void context.close().catch(() => {});
    return false;
  }
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
  const timer = setTimeout(() => {
    if (phase === 'transcribing') hint.textContent = 'Still checking what you said…';
  }, 6500);
  try {
    const speechQuery = '/api/speech/transcribe?language=' + capture.lang +
      (capture.lang === 'auto' && lastSpeechLanguage === 'rw' ? '&language_hint=rw' : '');
    const result = await api(speechQuery, {
      method: 'POST', body: form,
    });
    lastSpeechLanguage = result.detected_language || null;
    if (result.needs_confirmation) {
      const lang = result.detected_language === 'rw' || capture.lang === 'rw' ? 'rw' : 'en';
      const message = lang === 'rw' ? 'Sinumvise neza. Wabivuga nanone?' :
        'I didn’t catch that clearly. Could you say it again?';
      const reply = bubble(message, 'bot', lang);
      setPhase('idle', message);
      void speak(message, lang, reply);
      return;
    }
    await ask(result.text, capture.lang);
  } catch (error) {
    bubble('Speech recognition: ' + error.message);
    setPhase('idle', 'Try the microphone again or type a question.');
  } finally {
    clearTimeout(timer);
  }
}

record.addEventListener('click', async () => {
  if (phase === 'recording' && recording?.recorder.state === 'recording') {
    finishTurn(recording);
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
    const autoEnd = watchForPause(capture);
    setPhase('recording', autoEnd ?
      'Listening… Pause to send, or tap again.' : 'Recording… Tap again to send.');
    capture.timer = setTimeout(() => {
      finishTurn(capture);
    }, 30000);
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
