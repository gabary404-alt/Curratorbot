const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const vm = require('node:vm');
const {webcrypto} = require('node:crypto');

class Element {
  constructor() {
    this.children = [];
    this.listeners = {};
    this.value = '';
    this.classList = {toggle() {}, add() {}, remove() {}};
  }
  addEventListener(name, callback) { this.listeners[name] = callback; }
  setAttribute(name, value) { this[name] = value; }
  appendChild(child) { child.parent = this; this.children.push(child); return child; }
  append(child) { this.appendChild(child); }
  remove() {
    if (this.parent) this.parent.children = this.parent.children.filter(child => child !== this);
  }
  querySelector() { return null; }
}

const elements = new Map();
const element = id => {
  if (!elements.has(id)) elements.set(id, new Element());
  return elements.get(id);
};
const config = {
  mode: 'rehearsal', speech_input: ['rw', 'en'], speech_output: ['rw', 'en'],
};
const requests = [];
const timers = new Map();
let timerId = 0;
let audioPlays = 0;
let audioPauses = 0;
let stoppedTracks = 0;
let pendingTts;
let speechRequests = 0;
let useDeferredTts = false;
let microphoneError = null;
let capture;
let utterances = [];
let audioLevel = 0;
let clock = 0;
let sampleAudio;
let audioContextCloses = 0;
let transcription = {text: 'What is your name?'};

class Recorder {
  static isTypeSupported() { return true; }
  constructor() { this.mimeType = 'audio/webm'; capture = this; this.state = 'inactive'; }
  start() { this.state = 'recording'; }
  stop() {
    this.state = 'inactive';
    this.ondataavailable({data: new Blob(['clip'], {type: this.mimeType})});
    this.onstop();
  }
}

class Audio {
  constructor(url) { this.url = url; }
  play() { audioPlays++; this.onplaying?.(); return Promise.resolve(); }
  pause() { audioPauses++; }
}

element('lang').value = 'rw';
element('retrieval').value = 'auto';
const environment = {
  document: {getElementById: element, createElement: () => new Element()},
  crypto: webcrypto, AbortController, Blob, FormData,
  Audio, MediaRecorder: Recorder,
  SpeechSynthesisUtterance: class { constructor(text) { this.text = text; } },
  navigator: {mediaDevices: {async getUserMedia() {
    if (microphoneError) throw microphoneError;
    return {getTracks: () => [{stop() { stoppedTracks++; }}]};
  }}},
  setTimeout(callback) { timers.set(++timerId, callback); return timerId; },
  clearTimeout(id) { timers.delete(id); },
  setInterval(callback) { sampleAudio = callback; return 1; },
  clearInterval() { sampleAudio = null; },
  performance: {now: () => clock},
  window: {MediaRecorder: Recorder, speechSynthesis: {
    cancel() {}, getVoices: () => [{lang: 'en-US'}],
    speak(utterance) { utterances.push(utterance); utterance.onstart?.(); },
  }},
  async fetch(path, options = {}) {
    requests.push({path, options});
    let data;
    if (path === '/api/status') data = config;
    else if (path === '/api/speech/synthesize') {
      speechRequests++;
      if (useDeferredTts) data = await new Promise(resolve => { pendingTts = resolve; });
      else data = {audio_url: 'https://api.pindo.io/test.wav'};
    } else if (path.startsWith('/api/speech/transcribe')) data = transcription;
    else data = {reply: 'Currator', simulated: true, sources: []};
    return {ok: true, json: async () => data};
  },
};
const context = vm.createContext(environment);
vm.runInContext(readFileSync('src/currator/static/app.js', 'utf8'), context);
const flush = async () => {
  for (let i = 0; i < 20; i++) await Promise.resolve();
};
const value = source => vm.runInContext(source, context);

(async () => {
  await flush();
  assert.equal(element('status').textContent, 'Voice rehearsal');
  assert.equal(element('record').disabled, false);

  useDeferredTts = true;
  await value("ask('Muraho', 'rw')");
  await flush();
  assert.equal(speechRequests, 1);
  element('stop-audio').listeners.click();
  pendingTts({audio_url: 'https://api.pindo.io/old.wav'});
  await flush();
  assert.equal(audioPlays, 0);
  assert.equal(element('stop-audio').disabled, true);
  console.log('PASS Stop speech cancels a pending TTS response');

  useDeferredTts = false;
  await value("ask('Muraho', 'rw')");
  await flush();
  assert.equal(audioPlays, 1);
  element('lang').value = 'en';
  element('lang').listeners.change();
  assert.ok(audioPauses > 0);
  console.log('PASS Language change interrupts playback');

  await element('record').listeners.click();
  assert.equal(element('lang').disabled, true);
  assert.equal(element('send').disabled, true);
  assert.equal(value('phase'), 'recording');
  assert.equal(timers.size, 1);
  // Even an external language change cannot change the captured recording's language.
  element('lang').value = 'rw';
  await element('record').listeners.click();
  await flush();
  assert.ok(requests.some(request => request.path === '/api/speech/transcribe?language=en'));
  assert.ok(requests.some(request => request.path === '/api/chat' &&
    JSON.parse(request.options.body).language === 'en'));
  assert.equal(stoppedTracks, 1);
  assert.equal(timers.size, 0);
  assert.equal(value('phase'), 'idle');
  assert.equal(utterances.length, 0);
  assert.equal(element('face')['data-state'], 'speaking');
  console.log('PASS Recording keeps its language and releases microphone tracks');

  await element('record').listeners.click();
  capture.onerror();
  await flush();
  assert.equal(stoppedTracks, 2);
  assert.equal(value('phase'), 'idle');
  assert.equal(timers.size, 0);
  console.log('PASS Recorder error releases tracks and resets controls');

  microphoneError = Object.assign(new Error(), {name: 'NotAllowedError'});
  await element('record').listeners.click();
  assert.equal(value('phase'), 'idle');
  assert.match(element('hint').textContent, /permission was denied/);
  console.log('PASS Microphone permission failure returns to text input');

  microphoneError = null;
  environment.window.AudioContext = class {
    state = 'running';
    createMediaStreamSource() { return {connect() {}, disconnect() {}}; }
    createAnalyser() {
      return {getFloatTimeDomainData(samples) { samples.fill(audioLevel); }};
    }
    async resume() {}
    async close() { audioContextCloses++; }
  };
  const sample = (level, count) => {
    audioLevel = level;
    for (let i = 0; i < count; i++) {
      clock += 50;
      sampleAudio();
    }
  };
  const beforeTurn = requests.filter(request => request.path === '/api/chat').length;
  await element('record').listeners.click();
  sample(0, 22);
  assert.equal(value('phase'), 'recording');
  sample(0.08, 6);
  sample(0, 8);
  assert.equal(value('phase'), 'recording');
  sample(0.06, 6);
  sample(0, 18);
  await flush();
  assert.equal(value('phase'), 'idle');
  assert.equal(requests.filter(request => request.path === '/api/chat').length, beforeTurn + 1);
  assert.equal(audioContextCloses, 1);
  assert.equal(sampleAudio, null);
  console.log('PASS A pause after speech sends one turn and releases the microphone');

  transcription = {text: 'Nagiye i Kigali', detected_language: 'rw', needs_confirmation: true};
  await element('record').listeners.click();
  await element('record').listeners.click();
  await flush();
  assert.equal(element('prompt').value, '');
  assert.equal(requests.filter(request => request.path === '/api/chat').length, beforeTurn + 1);
  assert.ok(element('conversation').children.some(entry => /Wabivuga nanone/.test(entry.textContent)));
  assert.equal(JSON.parse(requests.at(-1).options.body).language, 'rw');
  console.log('PASS Unclear Kinyarwanda asks for a spoken retry without filling the composer');

  const tail = 'extra words '.repeat(100).trim();
  const begin = requests.length;
  const plays = audioPlays;
  context.tail = tail;
  const longReply = value("speak('Intro. ' + tail, 'en', document.createElement('div'), 'intro.wav', tail)");
  await flush();
  assert.equal(audioPlays, plays + 1);
  assert.equal(requests.length, begin + 1);
  value('speech.player.onended()');
  await flush();
  assert.equal(audioPlays, plays + 2);
  value('speech.player.onended()');
  await longReply;
  assert.equal(audioPlays, plays + 3);
  assert.equal(requests.slice(begin).map(r => JSON.parse(r.options.body).text).join(' '), tail);
  value('speech.player.onended()');
  console.log('PASS Long replies prefetch the next clip and speak the complete text in order');
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
