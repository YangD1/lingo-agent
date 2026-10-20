# transform: rewrite a sentence

Fields: `instruction` and an English `source` sentence; `accepted` lists right
rewrites, best first.

- The instruction says what to change in meaning or structure ("Say it in the
  passive.", "Join the two sentences into one.", "Report what she said."), not which
  words to write or where to put them.
- Do not give the tested form or a required opening that already contains it. A
  required opening is fine only when it is not the answer and is grammatical as it
  stands (with its subject: "I had my bike ..." not "had my bike ...").
- The rewrite must need the grammar point. If the learner could satisfy the
  instruction with a different structure, either accept it or narrow the instruction.
- `accepted` holds every natural correct rewrite, each one using the grammar point.
- A word in brackets or a word the learner must use is fine only when the point is
  how to use it (its position, its form). If choosing that word is the point (ever /
  never, much / far, since / for), or the source already has the tested form so the
  learner only adds the word, the item tests nothing: describe the meaning instead.
- For a contrast between two tenses (present perfect / past simple, past simple / past
  continuous), the learner must be able to pick the wrong one of the pair. Start from
  one of the two and ask for a change that needs the other; moving a present simple to
  "yesterday" only tests the past simple.
- For an article point (a / an / the / no article), the learner must choose the
  article. The source must not already hold it, the instruction must not open the
  answer with it ("Begin with The advice"), and joining two sentences is the wrong
  task: the work becomes the relative clause. Ask for a change that moves the article
  decision instead, such as a possessive into an of-phrase - only where the of-phrase
  is what people say (the history of Paris, the price of oil), never with a person
  ("the name of Mary").

Good (adverbs of frequency):
- source: "You are happy. (always)"
- instruction: "Rewrite the sentence with the word in brackets."
- accepted: "You are always happy.", "You're always happy."

Bad:
- instruction: "Add always after are and rewrite the sentence."
- Why it fails: the position after "are" is the rule; the learner just copies it.

Bad (present perfect for experience):
- source: "I have been to Japan." instruction: "Rewrite the sentence with never."
- Why it fails: the present perfect is already there and the word is given; the
  learner only drops "never" in.
  Better: source "This is my first time on a plane.", instruction "Say the same thing,
  starting with I.", accepted "I have never been on a plane before.", "I've never
  flown before."

Bad (present perfect / past simple):
- source: "I walk to school every day." instruction: "Make it about yesterday."
- Why it fails: only the past simple can be right; nothing tempts the present perfect.
  Better: source "I have seen that film.", instruction "Add that it was last
  Saturday.", accepted "I saw that film last Saturday.", "I saw it last Saturday."
  ("I have seen that film last Saturday" is the mistake the item catches.)

Bad (articles with specific reference):
- source: "You gave me some advice. It was helpful." instruction: "Rewrite as one
  clause beginning with The advice."
- Why it fails: the instruction gives "The", and what is left is a relative clause.
  Better: source "Paris's history is fascinating.", instruction "Say the same thing
  with of Paris after history.", accepted "The history of Paris is fascinating."
  ("History of Paris is fascinating" is the mistake the item catches.)

Bad (modifiers of comparatives):
- source: "This phone is more expensive than that one." instruction: "Use much to
  make the difference bigger."
- Why it fails: choosing much (not very) is the point, and the instruction gives it.
  Better: source "This phone costs £800. That one costs £200.", instruction "Compare
  the two phones in one sentence and show that the difference is big.", accepted
  "This phone is much more expensive than that one.", "... far / a lot more
  expensive ..."

Bad:
- source: "The girl lives next door. She is my friend."
- instruction: "Join with who, starting with 'The girl who lives next door'."
- Why it fails: the opening is the whole relative clause; only "is my friend" is left.
  Better: "Join the two sentences into one, using who."
