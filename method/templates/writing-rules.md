## Writing the text a person reads

**Every sentence a PERSON READS.** The list of fields used to be closed — `purpose`, `trigger`, `outcome`,
a rule `statement`, a `risk`, a `used_for`, a `wants`, a glossary meaning — and it was read as
exhaustive, so an agent authoring 45 `evidence[].why` lines had no idea whether these rules applied
and guessed. They do. The test is not which field it is: it is whether the sentence reaches a reader
in the viewer. If it does, it obeys these rules; a step `phrase`, a flow step's `phrase`, an
`evidence[].why` and a component `purpose` are all the same job.

A closed vocabulary would have to be re-checked against the model every time a field is added, and
it was not. What is NOT governed: ids, anchors, code links, and closed-vocabulary cells (`kind`,
`side`, `confidence`) — those are labels or machine values, and a word limit on a label is
meaningless.

Each of those sentences is read ONE BOX AT A TIME. The reader does not read
code, and has no paragraph around the box to lean on. Six rules:

1. **One idea per sentence, at most 20 words.** Two clauses joined by "and" are two sentences.
2. **No em dash.** Write the word that names the link: because, but, so, for example. In a
   one-sentence field a dash hides which of those you meant.
3. **No code in plain text.** No file path, no `name()`, no `--flag`, no snake_case identifier. The
   box already carries the code link, so the sentence exists to say what the thing DOES. A literal
   you must quote goes in backticks, which the check reads as a quotation rather than a name.
4. **Every reference resolves inside the same box.** The box is the unit of reading. A referring
   expression — "it", "this", "that X", "either X", "both", "the other", "such", "the same" — must
   point at something NAMED EARLIER IN THE SAME BOX. Within the box it is good prose: "…discovers
   each MCP's tools, then keeps that list fresh" is fine, and flattening it would be a loss. A
   reference whose antecedent lives in another box, or only in your head, is a defect: replace it
   with the names, or with the glossary words. Bad: "Mounting the MCP servers a team shares, in
   either kind" — the two kinds are named nowhere in the box. Good: "…a remote server at an
   address, or a command run for the team in a sandbox". The special case: an OPENING "It", "This",
   "That" or "They" can never resolve in-box, so never open with one.
5. **Use a glossary word, or add one.** A term the reader has not met belongs in the Glossary, never
   explained a second time in a second box.
6. **Plain words at the SAME precision.** "The system checks the user" is short and useless. Buying
   shortness by dropping the specific is worse than a long sentence.

## Naming an element

A NAME is not a sentence. It is a LABEL, read on a card, in a breadcrumb and in a column of other
names, never inside prose. So:

7. **No leading article.** "Dashboard", not "The dashboard". The article reads as a sentence
   fragment, and it costs a column of alignment against every name beside it. The exception is a
   real proper name: a product actually called *The Gateway* keeps its article, and that decision
   is recorded as `In: <why>` under a **"Naming exceptions"** extras heading.
8. **A name is the READER's word, never the class's spelling** (`source` already carries that), which
   is a rule because one map named 52 of 59 records after their classes and 0 of 126 components,
   while coyomap's own map does it 0 times in 222; a dependency keeps its vendor's name and a
   `non_entity_types` row exists to print a code type, so neither is governed, and a domain term
   really spelled that way is recorded as `<id>/code-name: <why>` under the same heading.

Measured when rule 7 landed, which is why it is a rule and not a preference: across the two live
maps, components 0 of 138, entities 0 of 171, dependencies 0 of 49, use cases 0 of 80, roles 0 of 9
and capabilities 0 of 17 began with "The" — while INTERFACES were 7 of 12 on one map and 3 of 11 on
the other. One element type had drifted off a convention 360-odd names already kept, and it was not
even consistent with itself. Note what the surfaces that skipped the article had in common: a proper
name, a plural, a mass noun. The article was doing grammar, never meaning.

`coyomap validate` counts rules 1 to 4, 7 and 8, and reports them as advisories, so a build gets numbers
back rather than an opinion. Of rule 4 it counts the checkable part: an opening pointer word, and a
mid-sentence "either / both / such / the other" + category noun with no two alternatives named in
the same box. The rest of rule 4, and rules 5 and 6, are yours to obey.
