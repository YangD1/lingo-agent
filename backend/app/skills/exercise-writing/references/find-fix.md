# find_fix: find the wrong piece and fix it

Fields: `segments`, the sentence in 3-6 consecutive pieces that join into it exactly
(each piece carries its own spaces and punctuation); `error_kind`, the kind of error
you planted (`form` or `word_choice`), written before you mark it; exactly one piece
has an error on the grammar point, at `wrong_segment` (0-based); `accepted` lists the
right replacements for that piece. Every other piece is correct.

- Only errors of **form or word choice**: a wrong ending, a wrong tense, a wrong
  pronoun, the wrong word of a pair (bored / boring). The wrong piece contains the
  wrong word.
- Never a **missing** word: "He eating now" can be fixed in "He " or in "eating ",
  so the wrong piece is not unique. Use `cloze` or `transform` for missing words.
- Cut the sentence so the error sits inside one piece, with its neighbours correct on
  their own. Do not split the tested form across two pieces.
- Plant exactly one error; check that every other piece is right as it stands.
- The error is in the grammar, never only in the spelling. "runing", "siting",
  "studing" have the right form with a spelling slip (a doubled consonant, y to ie):
  they test spelling rules, not the grammar point. Pick a verb whose form has no
  spelling change, or plant a wrong form ("is read" for "is reading").

Good (third person -s):
- segments: "My brother ", "work ", "in a bank ", "near our house."
- wrong_segment: 1
- accepted: "works "

Bad:
- segments: "He ", "eating ", "now."
- Why it fails: the error is a missing "is", which could go into either of the first
  two pieces.

Bad (present continuous):
- segments: "I ", "am runing ", "now."
- Why it fails: "am" + -ing is already right; only the doubled n is missing, so the
  item tests spelling.
  Better: "She ", "is read ", "a book in the garden now.", accepted "is reading ".
