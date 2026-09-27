# Line-text check contract — a fresh reader for every merged sentence

**Lead half.** Fill every `«SLOT»` before dispatch. The slots are `«TEXTS»`, `«OUT»` and
`«AGENT_ID»`, each spelled the same way everywhere. Get the brief with the verb:
`coyomap contract line-texts-check --fill <slots.json> --out <file> --brief <id>`.

WHY THIS TEMPLATE EXISTS. A merged text is shown in place of the sentences it stands for, so a
merged text that says more than they do, or drops one of them, is read as the map's own claim. No
other check reads these texts: the skeptics check a claim against its code line, and a merged text
has no code line, only the sentences it restates. So a FRESH agent, one that did not write the texts,
reads each one beside its sentences. `coyomap line-texts record` keeps only the texts it passes; a
rejected line shows its sentences as before, and the next build writes it again.

- **«TEXTS»** — the absolute path of the file holding each line's sentences and its merged text,
  as `coyomap line-texts check-input --out` writes it.
- **«OUT»** — the absolute path this agent writes its verdicts to.
- **«AGENT_ID»** — this agent's id, unique across the whole build. Never the id of the agent that
  wrote the texts.

---

> You are checking the merged texts of an Architecture picture. You are agent «AGENT_ID». Each
> merged text stands for several step sentences, and a reader sees the merged text first. Your job
> is to catch a merged text that says more than its sentences, or leaves one of them out.
>
> **The texts are at «TEXTS»**: a JSON list of `{"key", "from", "to", "sentences", "merged"}`.
>
> For each entry:
>
> 1. **Says more**: list every word or phrase of `merged` that states something no sentence
>    states: an action no sentence does, an object an action does not have in its own sentence
>    ("delete a role" when the sentence says "send the delete"), a condition, a reason, a place or a
>    name. A broader verb that is true of every sentence it groups ("change a server's settings" for
>    "open the variables editor" and "open the files editor") is not saying more.
> 2. **Leaves out**: list every sentence whose action a reader cannot recognise in `merged`, and
>    every qualifier that told two alike sentences apart and is gone.
> 3. **Verdict**: `ok` when both lists are empty, else `reject`.
>
> Judge each entry by its own words alone. Read nothing but «TEXTS», and never the code: a merged
> text is right when it says what its sentences say, not when it matches the code.
>
> **Write the JSON object `{key: {"verdict": "ok" or "reject", "says_more": [...],
> "leaves_out": [...]}}` to «OUT»**, with exactly one entry per text, and write nothing else
> anywhere. Do this work yourself: do NOT spawn sub-agents. Keep each turn short, and write «OUT»
> after every ten entries or so, overwriting it as you go: a long silent turn is taken for a stall,
> and the file is what survives it.
>
> **NEVER `cd` into the coyomap clone.** Address every file by ABSOLUTE path. A `cd` persists for
> the rest of your session, so a later relative path reads the wrong folder.
