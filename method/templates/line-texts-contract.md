# Line-text contract — one merged sentence per Architecture line

**Lead half.** Fill every `«SLOT»` before dispatch. The slots are `«COYOMAP_HOME»`, `«LINES»`,
`«OUT»` and `«AGENT_ID»`, each spelled the same way everywhere. Get the brief with the verb:
`coyomap contract line-texts --fill <slots.json> --out <file> --brief <id>`.

WHY THIS TEMPLATE EXISTS. The Architecture picture merges many stories, so one line between two
boxes carries one step sentence per story that takes it. On mcpolis's All picture, 62 of 113 lines
carried 2 or more, and 106 sentences sat behind "+N more": a reader saw 2 of a line's actions. One
merged sentence per line shows all of them in about the same reading. A trial on 96 lines wrote 92
right; the 4 wrong ones gave an action an object its sentence did not name, or dropped a sentence
from a long line, and rules 1 and 2 below name both. The merged texts are checked by a fresh agent
(`line-texts-check`) before `coyomap line-texts record` keeps any of them.

- **«LINES»** — the absolute path of the pending lines file `coyomap line-texts pending --out` wrote.
- **«OUT»** — the absolute path this agent writes its `{key: merged text}` object to.
- **«AGENT_ID»** — this agent's id, unique across the whole build.
- **«COYOMAP_HOME»** — the coyomap clone the build runs from.

---

> You are writing the merged texts of an Architecture picture: one sentence for each line that
> several stories take, telling a reader what crosses that line. You are agent «AGENT_ID».
>
> **The lines are at «LINES»**: a JSON list of `{"key", "from", "to", "sentences"}`. `from` and
> `to` are the two boxes the line joins. `sentences` are the step sentences of the stories that take
> the line, one per distinct sentence. `drawn_as`, when present, is every pair of boxes the same
> line joins: one picture can show a whole subsystem where another shows one of its parts.
>
> **Rules for the merged text**
>
> 1. **Use only what the sentences say.** Never add a fact, a reason, a condition, a place or a
>    name that no sentence states. **Never give an action an object its sentence does not name**:
>    "send the delete" is not "delete a role". When in doubt, leave it out.
> 2. **Cover every sentence.** A reader must recognise each sentence's action in the merged text.
>    Group actions that share an object: "start, stop or sign in to the server". Keep what tells two
>    alike sentences apart ("every server, or only those whose sign-in is close to expiring"). When
>    20 words cannot hold every action, group them under a broader verb that is true of each one
>    ("edit a server's settings"), never drop one.
> 3. **The sentences are alternatives, not steps in order.** They come from different stories, and
>    each story takes the line once. Join them with "or", never with "then" or "and then".
> 4. **Write an action, in the imperative, with no subject**, the way the sentences are written:
>    "add a server", never "adds a server" or "the admin adds a server".
> 5. **One sentence, at most 20 words, plain words.** No dash, no semicolon, no code-shaped word
>    (no function, file or field names), and never start with "It" or "This".
> 6. **Do not name a box of the line, on any picture.** The picture already shows it, and on
>    another picture the same line can join a different box. Keep another name only when a sentence
>    needs it to make sense.
> 7. **When the sentences share nothing**, name the two or three main actions joined with "or", and
>    keep each one short.
>
> **Write the JSON object `{key: merged text}` to «OUT»**, with exactly one entry per line, and
> write nothing else anywhere. Read nothing but «LINES». Do this work yourself: do NOT spawn
> sub-agents, and do NOT write a program that writes the texts. Keep each turn short, and write
> «OUT» after every ten lines or so, overwriting it as you go: a long silent turn is taken for a
> stall, and the file is what survives it.
>
> **Before you return, check your file** with
> `«COYOMAP_HOME»/.venv/bin/coyomap line-texts lint --lines «LINES» «OUT»`. It checks the rules no
> reader is needed for: a line with no text, a text for no line, a second sentence, more than 20
> words, a dash, a semicolon, "then", an opening "It" or "This", a code-shaped word. Fix every line
> it names and run it again, until it prints `clean`. A fresh agent then reads each text beside its
> sentences for rules 1 and 2, which no tool can check.
>
> **NEVER `cd` into the coyomap clone.** Address every file by ABSOLUTE path. A `cd` persists for
> the rest of your session, so a later relative path reads the wrong folder.
