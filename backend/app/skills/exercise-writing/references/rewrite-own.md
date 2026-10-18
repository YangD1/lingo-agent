# rewrite_own: correct the learner's own sentence

Fields: `instruction` and `accepted`. The learner wrote `learner_sentence.original` and
got the grammar point wrong; the sentence is shown to them next to the instruction, so
do not repeat it.

- A short instruction asking them to correct their sentence ("Correct your sentence
  so it talks about a finished time in the past."). Point to what is wrong in meaning,
  not to the fix.
- `accepted` lists corrected versions that keep their meaning and wording as far as
  possible, best first. Change only what the grammar point needs.
