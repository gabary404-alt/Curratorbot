# Currator Kinyarwanda language and speech evaluation

Currator uses instruction tuning at inference time through a language guide and original
examples. The introduction of a second recognizer does not update Gemini or Pindo model weights.
When the recognizers disagree substantially, differ on some critical words, or Gemini flags
unclear speech, the app asks the speaker to repeat the question. Mixed-language speech stays with the multilingual recognizer.

## Teaching references

- [Rwanda Cultural Heritage Academy](https://tumenye-ikinyarwanda.rwandaheritage.gov.rw/)
  distinguishes greetings, registers, idioms, and riddles. Use this for cultural and
  conversational register.
- [REB P1 course](https://uat-coremis.reb.rw/course/view.php?id=237) and
  [REB P6 book](https://uat-coremis.reb.rw/pluginfile.php/15548/mod_resource/content/2/kinyarwanda%20P6%20SB.pdf?forcedownload=1)
  provide classroom sequences and examples of reading, punctuation, and agreement.
  The original REB portal course link timed out. The REB alternative was accessible.
- [Kinyarwanda.com dictionary](https://kinyarwanda.com/translate) and
  [Kinyarwanda.org](https://kinyarwanda.org/) are useful for checking a term in context
  and finding oral literature. Dictionary translations need sentence context.
- [Kinyarwanda Online](https://www.kinyarwanda-online.com/courses),
  [RundiRwanda](https://rundirwanda.com/about-rundirwanda),
  [Memrise](https://www.memrise.com/en/learn-kinyarwanda), and
  [Kigali School](https://kigalischool.com/) suggest progression from vocabulary
  and greetings to natural follow-up questions. Keep Kirundi examples separate.
- [Everyday greetings video](https://www.youtube.com/watch?v=kGd4IKGzuJ8) and
  [compound consonant pronunciation video](https://www.youtube.com/watch?v=lE67wTWDaeM)
  identify topics for a pronunciation checklist. Video descriptions were accessible.
  Use licensed, transcribed recordings for speech metrics and training data.
- [Mozilla Common Voice](https://commonvoice.mozilla.org/rw/datasets) lists a CC0
  Kinyarwanda corpus. [Digital Umuganda Afrivoice](https://huggingface.co/datasets/DigitalUmuganda/Afrivoice_Kinyarwanda)
  and [its public sample](https://huggingface.co/datasets/badrex/kinyarwanda-speech-sample)
  offer additional speech data. Record the exact release, license, and test split.

## Original rehearsal prompts

| Area | Say this | What to check |
| --- | --- | --- |
| Greeting | Muraho neza! Witwa nde? | Identify Currator and respond warmly in Kinyarwanda |
| Agreement | Umwana muto arakina. Bivuge mu bwinshi. | Abana bato barakina |
| Possession | Ni irihe tandukaniro riri hagati y'igitabo cyanjye n'ibitabo byanjye? | Singular, plural and possessive agreement |
| Negation | Sinagiye i Kigali. Nagiye i Musanze. | Preserve the negation and both place names |
| Names | Ese uzi aho Nyabihu iherereye? | Preserve Nyabihu and answer the place question |
| Reasoning | Dufite imyembe cumi n'ibiri. Abantu bane bayigabanye, buri wese abona ingahe? | Three each and a short explanation |
| Code-switching | Mbwira muri make icyo USB ikora. | Preserve USB and keep the reply in Kinyarwanda |
| Register | Nsobanurira ijambo ikeshamvugo, umpe urugero rumwe. | One contextual example |
| Idiom | Iyo umuntu avuze ngo yakubise amaso ku kintu, aba ashaka kuvuga iki? | Explain seeing or noticing in context |
| Noise | Repeat a prompt while another person speaks softly nearby. | Show an editable transcript or request a retry when needed |

## Measure on recordings

Create a UTF-8 TSV with columns `audio` and `reference`. Use paths relative to the TSV.
Record at least three native speakers, with both read prompts and spontaneous turns. Ask a
native reviewer to transcribe the spontaneous turns before running the test. Keep speakers
used for final validation separate from examples used to tune the app.

```text
python -m currator.kinyarwanda_eval recordings.tsv --language auto
python -m currator.kinyarwanda_eval recordings.tsv --language rw
```

The evaluator shows per-clip errors, latency, aggregate word error rate, how often the app
requested review, and failed clips. Read the transcripts to check names, numbers, negation,
and code-switches separately. Have native speakers also rate the spoken output for
pronunciation, rhythm, grammar, and how natural it feels. Run on the pitch laptop, microphone,
speakers, and network. Select the production speech route based on those results.

On November 23, 2026, Pindo alone completed the first four labeled validation rows of the
public Afrivoice sample. It made 26 word edits over 98 reference words (26.5% word error
rate), with request times of 0.8 to 1.5 seconds. This small read-speech baseline does not
measure the two-recognizer flow or pitch conditions. The first four public test rows had
empty references and were excluded from scoring.

If an existing recognizer is inadequate, benchmark a specialist checkpoint separately on
the same recordings before choosing a candidate for local fine-tuning. Keep pitch speakers
out of the model's training data and retain a separate noisy-room test.
