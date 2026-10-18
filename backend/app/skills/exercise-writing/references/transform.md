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

Good (adverbs of frequency):
- source: "You are happy. (always)"
- instruction: "Rewrite the sentence with the word in brackets."
- accepted: "You are always happy.", "You're always happy."

Bad:
- instruction: "Add always after are and rewrite the sentence."
- Why it fails: the position after "are" is the rule; the learner just copies it.

Bad:
- source: "The girl lives next door. She is my friend."
- instruction: "Join with who, starting with 'The girl who lives next door'."
- Why it fails: the opening is the whole relative clause; only "is my friend" is left.
  Better: "Join the two sentences into one, using who."
