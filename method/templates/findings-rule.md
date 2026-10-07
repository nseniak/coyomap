**A finding about the product goes in your findings file, the moment you see it.** Your job may
show you something it does not ask about: a bug, a risk (to security, privacy, money or data), a
gap (a check that is missing, a path nothing guards) or a contradiction (two parts of the code, or
the code and its own docs, that disagree). File each one with one command, naming only files you
opened yourself:

    «COYOMAP_HOME»/.venv/bin/coyomap findings add --repo «REPO» --agent «AGENT_ID» \
      --kind <bug|risk|gap|contradiction> --where <path>:<line> \
      --text "<what the code does, and why it matters>"

`--where` repeats when a finding spans files. Filing writes only your own file under
`.coyomap/findings/` and changes nothing in the code or the map; the command is how a finding gets
there, so never open or edit that folder yourself. Do not carry a finding in your
report instead: a report can be lost on the way, and this file is collected by a tool. Do not file
what your output already records (a refuted claim, a gap row, a rule). End your report with
`findings: <the number you filed>`.
