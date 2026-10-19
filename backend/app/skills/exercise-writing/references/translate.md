# translate: from the learner's language into English

Fields: `source`, a sentence in the learner's language whose natural English
translation needs the grammar point; `instruction` names the structure to use, or
null; `accepted` lists good translations, best first.

- Choose a sentence whose most natural translation needs the grammar point. If the
  natural translation does not, pick another sentence rather than forcing it with the
  instruction.
- Then translate the source the plainest way you can **without** the grammar point
  (another verb, another structure, the active instead of the passive). If that
  translation is natural and correct, the question does not test the point: rule it
  out in the source, or say in the instruction what meaning to keep (who does what,
  what the speaker arranged - never the form), or pick another sentence.
- The instruction may say what kind of meaning to express ("talk about the music in
  this particular film") but must not give the tested word or form ("use boring",
  "use has").
- `accepted` holds every natural correct translation that uses the grammar point. Do
  not list a translation with a different structure (have got for have, going to for
  will) unless it also tests the point.

Good (-ed / -ing adjectives):
- source (Chinese): "这部电影很无聊，我都快睡着了。"
- instruction: null
- accepted: "This film is so boring that I'm almost falling asleep.", ...
- Why it works: the film causes the feeling, so the learner must choose boring.

Bad (causative have / get):
- source: "我昨天找人修了自行车。" accepted: "I had my bike repaired yesterday."
- Why it fails: "I asked someone to repair my bike yesterday." is just as natural and
  correct, and needs no causative.

Good (causative have / get):
- source: "我的手机屏幕碎了，下午拿去店里换。"
- instruction: "Make yourself the subject, and don't say who does the repair."
- accepted: "My phone screen is broken, so I'm going to have it replaced this
  afternoon.", "... get it replaced this afternoon."
- Why it works: the instruction gives the meaning (you arrange it, someone else does
  it), not the form; "I'm going to replace it" would mean you do it yourself.

Bad:
- source: "这部电影很无聊。" instruction: "Use boring to describe the film."
- Why it fails: the instruction makes the choice for them.

Bad:
- source: "他有两只猫。" instruction: "Use the present simple of have."
  accepted: "He has two cats.", "He's got two cats."
- Why it fails: "He's got" is not the present simple of have; list only answers that
  use the grammar point.
