# grounding lint counts one file opened under several spellings as one file

Change (2026-10-08, round 2, retro finding mcpolis-2026-10-08-#13): `grounding lint
--agent-transcripts` no longer flags a row that cites a file by its bare name when the agent opened
that file under several spellings (absolute, from the repo root, from a subfolder). A spelling that
is a path ending of another counts as that file, so only two DIFFERENT files with the name stay
ambiguous · tools/coyomap/grounding.py (`_resolves`), tests/test_grounding.py.

## Checks

1. expect: on the 2026-10-08 mcpolis verdicts and transcripts the "worth a second look" note reads
   27 rows over 15 files, down from 51 rows over 25 files; the 8 names the retro saw opened
   (app.py, invitations.py, org_routes.py, org_service.py, service_token_pin.py,
   service_token_service.py, service_token_verifier.py, session_owner_guard.py) are not in it.
   regression sign: any of those 8 names in the note on that data, or a file the note lists that
   `_opened_files` shows under a spelling that is a path ending of the cited one.

2. expect: on the next build, every file the note lists is one no file-reading tool call of the
   pass opened under any spelling (spot-check 5).
   regression sign: a listed file whose `Read`, `sed -n` or `cat` call is in a skeptic's
   transcript.

## Review fix (2026-10-08)

A path ending merged two spellings even when both are files of the repo: `index.ts` read as
`src/index.ts` and `packages/foo/src/index.ts` counted as one file. With the repo known (from the
verdict files' `.coyomap/` folder), an absolute spelling is read from the repo root, and a shorter
spelling that is a repo file of its own stays a separate file. With no repo, a path ending is still
taken as the same file. On the 2026-10-08 mcpolis data the note is unchanged: 27 rows over 15
files · tools/coyomap/grounding.py, tests/test_grounding.py.

3. expect: on a repo with two files of one name where one path ends the other, a bare-name citation
   of that name is in the "worth a second look" note or the ghost list.
   regression sign: the lint silent on such a citation while only one of the two files was
   opened.
