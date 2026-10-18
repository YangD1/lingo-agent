# find_fix: find the wrong piece and fix it

Fields: `segments`, the sentence in 3-6 consecutive pieces that join into it exactly
(each piece carries its own spaces and punctuation); exactly one piece has an error on
the grammar point, at `wrong_segment` (0-based); `accepted` lists the right
replacements for that piece. Every other piece is correct.

- Only errors of **form or word choice**: a wrong ending, a wrong tense, a wrong
  pronoun, the wrong word of a pair (bored / boring). The wrong piece contains the
  wrong word.
- Never a **missing** word: "He eating now" can be fixed in "He " or in "eating ",
  so the wrong piece is not unique. Use `cloze` or `transform` for missing words.
- Cut the sentence so the error sits inside one piece, with its neighbours correct on
  their own. Do not split the tested form across two pieces.
- Plant exactly one error; check that every other piece is right as it stands.

Good (third person -s):
- segments: "My brother ", "work ", "in a bank ", "near our house."
- wrong_segment: 1
- accepted: "works "

Bad:
- segments: "He ", "eating ", "now."
- Why it fails: the error is a missing "is", which could go into either of the first
  two pieces.
