# translate: from the learner's language into English

Fields: `source`, a sentence in the learner's language whose natural English
translation needs the grammar point; `instruction` names the structure to use, or
null; `accepted` lists good translations, best first.

- Choose a sentence whose most natural translation needs the grammar point. If the
  natural translation does not, pick another sentence rather than forcing it with the
  instruction.
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

Bad:
- source: "这部电影很无聊。" instruction: "Use boring to describe the film."
- Why it fails: the instruction makes the choice for them.

Bad:
- source: "他有两只猫。" instruction: "Use the present simple of have."
  accepted: "He has two cats.", "He's got two cats."
- Why it fails: "He's got" is not the present simple of have; list only answers that
  use the grammar point.
